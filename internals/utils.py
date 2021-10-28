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
"""

from typing import Union

__all__ = (
    "get_indexed",
    "complex_walk",
)


def get_indexed(data: list, n: int):
    if not data:
        return None
    try:
        return data[n]
    except (ValueError, IndexError):
        return None


def complex_walk(dictionary: Union[dict, list], paths: str):
    if not dictionary:
        return None
    expanded_paths = paths.split(".")
    skip_it = False
    for n, path in enumerate(expanded_paths):
        if skip_it:
            skip_it = False
            continue
        if path.isdigit():
            path = int(path)  # type: ignore
        if path == "*" and isinstance(dictionary, list):
            new_concat = []
            next_path = get_indexed(expanded_paths, n + 1)
            if next_path is None:
                return None
            skip_it = True
            for content in dictionary:
                try:
                    new_concat.append(content[next_path])
                except (TypeError, ValueError, IndexError, KeyError, AttributeError):
                    pass
            if len(new_concat) < 1:
                return new_concat
            dictionary = new_concat
            continue
        try:
            dictionary = dictionary[path]  # type: ignore
        except (TypeError, ValueError, IndexError, KeyError, AttributeError):
            return None
    return dictionary
