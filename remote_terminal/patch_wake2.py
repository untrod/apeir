#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第二补丁:把唤醒转写换成 VAD 过滤+强制英文+抑制幻觉。幂等。
   用法: python3 patch_wake2.py /opt/nous/brain.py"""
import os
import re
import sys
import io
import shutil
import ast
import base64

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "brain.py")
src = io.open(path, encoding="utf-8").read()
orig = src

NEW_BLOCK = base64.b64decode(
    "ICAgICAgICAgICAgaWYgaGludCA9PSAid2FrZSI6CiAgICAgICAgICAgICAgICB3YWtlX2t3ID0gZGljdChsYW5ndWFnZT0iZW4iLCBiZWFtX3NpemU9NSwgdGVtcGVyYXR1cmU9MC4wLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgY29uZGl0aW9uX29uX3ByZXZpb3VzX3RleHQ9RmFsc2UsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBub19zcGVlY2hfdGhyZXNob2xkPTAuNiwgbG9nX3Byb2JfdGhyZXNob2xkPS0xLjAsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBjb21wcmVzc2lvbl9yYXRpb190aHJlc2hvbGQ9Mi40KQogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIHNlZ21lbnRzLCBfID0gbW9kZWwudHJhbnNjcmliZSh0bXAubmFtZSwgdmFkX2ZpbHRlcj1UcnVlLCAqKndha2Vfa3cpCiAgICAgICAgICAgICAgICAgICAgcGFydHMgPSBbcy50ZXh0LnN0cmlwKCkgZm9yIHMgaW4gc2VnbWVudHMgaWYgcy50ZXh0LnN0cmlwKCldCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHNlZ21lbnRzLCBfID0gbW9kZWwudHJhbnNjcmliZSh0bXAubmFtZSwgKip3YWtlX2t3KQogICAgICAgICAgICAgICAgICAgIHBhcnRzID0gW3MudGV4dC5zdHJpcCgpIGZvciBzIGluIHNlZ21lbnRzIGlmIHMudGV4dC5zdHJpcCgpXQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VnbWVudHMsIF8gPSBtb2RlbC50cmFuc2NyaWJlKHRtcC5uYW1lLCBsYW5ndWFnZT0iemgiLCBiZWFtX3NpemU9NSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBjb25kaXRpb25fb25fcHJldmlvdXNfdGV4dD1GYWxzZSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpbml0aWFsX3Byb21wdD1Ob25lKQogICAgICAgICAgICAgICAgcGFydHMgPSBbcy50ZXh0LnN0cmlwKCkgZm9yIHMgaW4gc2VnbWVudHMgaWYgcy50ZXh0LnN0cmlwKCld"
).decode("utf-8")

if "vad_filter=True" in src:
    print("已是最新(含 vad_filter),跳过。"); sys.exit(0)

# 替换:从 transcribe 调用 到 紧随的 parts=[...] 行
pat = re.compile(
    r"[ \t]*segments, _ = model\.transcribe\(tmp\.name,.*?initial_prompt=\w+\)\s*\n"
    r"[ \t]*parts = \[s\.text\.strip\(\) for s in segments if s\.text\.strip\(\)\]",
    re.S)
src, n = pat.subn(lambda m: NEW_BLOCK, src, count=1)

if n == 0 or src == orig:
    print("未匹配到转写块,未改动。n=%d" % n); sys.exit(1)
ast.parse(src)
shutil.copyfile(path, path + ".bak2")
io.open(path, "w", encoding="utf-8").write(src)
print("已修补 %s (备份 .bak2)  转写块替换=%d" % (path, n))
