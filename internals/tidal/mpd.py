"""
MIT License

Copyright (c) 2021-present noaione

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

MPD parser
"""
from dataclasses import dataclass, field
from io import StringIO
from typing import List, Optional
from xml.etree import ElementTree as ET


@dataclass
class TidalMPDMetaChunk:
    number: int
    size: int

    def as_url(self, url: str):
        return url.replace("$Number$", str(self.number))


@dataclass
class TidalMPDMeta:
    initial: str
    template: str
    codecs: str
    mimetype: str
    chunks: List[TidalMPDMetaChunk] = field(default_factory=list)


def parse_mpd_string(mpd_string: str) -> Optional[TidalMPDMeta]:
    """Parse Tidal MPD string into a proper TidalMPDMeta object

    :param mpd_string: the mpd string from the API
    :type mpd_string: str
    :return: parsed MPD object
    :rtype: Optional[TidalMPDMeta]
    """

    mpd_io = StringIO(mpd_string)

    try:
        root = ET.parse(mpd_io).getroot()
    except ET.ParseError:
        return None

    if "mpd" not in root.tag.lower():
        return None

    select_tree: ET.Element = None
    for period in root:
        if "period" in period.tag.lower():
            for adaptation in period:
                if "adaptationset" in adaptation.tag.lower():
                    attribs = adaptation.attrib
                    if attribs.get("contentType", "unknown") == "audio":
                        select_tree = adaptation
                        break

    if select_tree is None:
        return None

    representations: ET.Element = list(select_tree)[0]
    codecs = representations.attrib.get("codecs", "unknown")
    mimetype = select_tree.attrib.get("mimeType", "unknown")

    segment_template: ET.Element = list(representations)[0]
    timeline: ET.Element = None
    for child in segment_template:
        if "segmenttimeline" in child.tag.lower():
            timeline = child
            break

    if timeline is None:
        return None

    initial: str = segment_template.attrib.get("initialization")
    if initial is None:
        return None

    template: str = segment_template.attrib.get("media")
    if template is None:
        return None

    timeline_chunks = list(timeline)
    total_chunks: List[TidalMPDMetaChunk] = []
    current_number = int(segment_template.attrib.get("startNumber", "0"))
    for chunk in timeline_chunks:
        if "s" in chunk.tag.lower():
            chunk_range = int(chunk.attrib.get("r", "1"))
            for _ in range(chunk_range):
                total_chunks.append(TidalMPDMetaChunk(current_number, int(chunk.attrib.get("d", "0"))))
                current_number += 1

    return TidalMPDMeta(
        initial=initial,
        template=template,
        codecs=codecs,
        mimetype=mimetype,
        chunks=total_chunks,
    )
