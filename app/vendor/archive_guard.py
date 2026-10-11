# Adapted from LearnMargin (MIT), Copyright (c) 2026 Southwall-Tester.
import os
import stat
import struct
import zipfile
import zlib
from urllib.parse import unquote
from pathlib import Path
from xml.parsers import expat

MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_MEMBER_BYTES = 50 * 1024 * 1024
MAX_ZIP_ENTRIES = 5000
ZIP_READ_CHUNK = 64 * 1024


class IngestionError(ValueError):
    pass


def _xml_guard():
    """Reject declarations in the XML parser, after its encoding detection."""
    parser = expat.ParserCreate()

    def reject(*_args):
        raise IngestionError("文档包含不支持的 XML 外部声明，请重新导出。")

    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    return parser


def _zip_chunks(raw, item: zipfile.ZipInfo, remaining_budget: int):
    """Validate the real compressed stream, not ZipInfo's attacker-controlled size.

    ZipExtFile truncates to file_size, and an unbounded read can inflate far more
    before that truncation. Validate independently with zlib's output limit; do
    not call flush(), whose output is unbounded.
    """
    raw.seek(item.header_offset)
    header = raw.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        raise IngestionError("文档压缩包的文件头损坏，请重新导出。")
    fields = struct.unpack("<4s5H3I2H", header)
    if fields[3] != item.compress_type or fields[2] != item.flag_bits:
        raise IngestionError("文档压缩包的文件头与目录不一致，请重新导出。")
    raw.seek(fields[-2] + fields[-1], os.SEEK_CUR)
    compressed_left = item.compress_size
    decoder = zlib.decompressobj(-zlib.MAX_WBITS) if item.compress_type == zipfile.ZIP_DEFLATED else None
    pending = b""
    actual = 0
    checksum = 0
    while compressed_left or pending:
        if not pending:
            pending = raw.read(min(ZIP_READ_CHUNK, compressed_left))
            if not pending:
                raise IngestionError("文档压缩包内容不完整，请重新导出。")
            compressed_left -= len(pending)
        # The extra byte detects false size declarations without first expanding
        # the whole member, even when its forged CRC matches the truncated data.
        limit = min(
            ZIP_READ_CHUNK,
            item.file_size - actual + 1,
            MAX_MEMBER_BYTES - actual + 1,
            remaining_budget - actual + 1,
        )
        if decoder:
            chunk = decoder.decompress(pending, max(1, limit))
            pending = decoder.unconsumed_tail
        else:
            chunk, pending = pending[: max(1, limit)], pending[max(1, limit) :]
        actual += len(chunk)
        if actual > MAX_MEMBER_BYTES or actual > remaining_budget:
            raise IngestionError("文档实际解压内容超过限制，请拆分材料再上传。")
        if actual > item.file_size:
            raise IngestionError("文档压缩包声明大小与实际内容不一致，请重新导出。")
        checksum = zlib.crc32(chunk, checksum)
        yield chunk
        if decoder and decoder.eof:
            if decoder.unused_data or pending or compressed_left:
                raise IngestionError("文档压缩包包含多余的压缩数据，请重新导出。")
            break
    if (decoder is not None and not decoder.eof) or actual != item.file_size or checksum != item.CRC:
        raise IngestionError("文档压缩包的实际内容与校验信息不一致，请重新导出。")


def _check_zip(path: Path) -> None:
    """Bound actual expansion and validate XML before using document libraries."""
    with zipfile.ZipFile(path) as archive, path.open("rb") as raw:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise IngestionError(f"压缩包条目过多，最多允许 {MAX_ZIP_ENTRIES} 项。")
        if sum(item.file_size for item in entries) > MAX_UNCOMPRESSED_BYTES:
            raise IngestionError("文档解压后超过 250 MB，请拆分材料再上传。")
        names: set[str] = set()
        offsets: set[int] = set()
        xml_parts: set[str] = set()
        xml_extensions: set[str] = set()

        def content_type(tag, attributes):
            if not attributes.get("ContentType", "").lower().endswith(("+xml", "/xml")):
                return
            if tag.rsplit(":", 1)[-1] == "Override":
                xml_parts.add(unquote(attributes.get("PartName", "")).lstrip("/"))
            elif tag.rsplit(":", 1)[-1] == "Default":
                xml_extensions.add(attributes.get("Extension", "").lower())
            if len(xml_parts) + len(xml_extensions) > MAX_ZIP_ENTRIES:
                raise IngestionError("文档包含过多的内容类型声明，请拆分材料再上传。")

        actual_total = 0
        # Read the guarded OOXML manifest first, regardless of ZIP entry order.
        # Relationships can assign XML content types to arbitrary suffixes.
        for item in sorted(entries, key=lambda entry: entry.filename != "[Content_Types].xml"):
            name = item.filename.replace("\\", "/")
            if (
                name.startswith("/")
                or ":" in name
                or ".." in name.split("/")
                or name in names
                or item.orig_filename != item.filename
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.header_offset in offsets
            ):
                raise IngestionError("文档压缩包包含不安全或重复的文件路径。")
            names.add(name)
            offsets.add(item.header_offset)
            if item.flag_bits & 1:
                raise IngestionError("无法读取加密的文档压缩包，请先保存为未加密副本。")
            if item.file_size > MAX_MEMBER_BYTES:
                raise IngestionError("文档内单个文件超过 50 MB，请缩小图片或拆分材料。")
            if item.file_size > 1024 * 1024 and item.file_size > max(1, item.compress_size) * 1000:
                raise IngestionError("文档压缩比例异常，请重新导出材料。")
            if item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise IngestionError("文档使用不支持的 ZIP 压缩方式，请用原应用重新导出。")
            if name.lower().endswith("vbaproject.bin"):
                raise IngestionError("暂不导入包含宏的 Office 文档，请另存为不含宏的副本。")
            # open() validates names, extra fields and overlapping compressed
            # ranges but deliberately never reads/decompresses member data here.
            with archive.open(item):
                pass
            is_xml = (
                name.lower().endswith((".xml", ".rels", ".opf", ".ncx"))
                or name in xml_parts
                or name.rsplit(".", 1)[-1].lower() in xml_extensions
            )
            xml = _xml_guard() if is_xml else None
            if name == "[Content_Types].xml":
                xml.StartElementHandler = content_type
            for chunk in _zip_chunks(raw, item, MAX_UNCOMPRESSED_BYTES - actual_total):
                actual_total += len(chunk)
                if xml is not None:
                    xml.Parse(chunk, False)
            if xml is not None:
                xml.Parse(b"", True)
