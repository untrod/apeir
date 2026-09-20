#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第三补丁: Siri 式唤醒优化 — 在吗Nous 检测 + 问候语区分 + 自动检测语言 + beam=1 加速。
   用法: python3 patch_wake3.py /opt/nous/brain.py   (幂等,先备份 .bak3)"""
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

# 幂等检测(以修复版独有的内嵌 _looks 为准,确保旧 patch3 也能被更新)
if "def _looks(s):" in src:
    print("已是最新(含修复版 _looks),跳过。")
    sys.exit(0)


# 1. 替换 _is_wake_word → 返回 (bool, greeting)

NEW_FUNC = base64.b64decode(
    "ZGVmIF9pc193YWtlX3dvcmQodGV4dDogc3RyKToKICAgICIiIuajgOafpei9rOWGmeaWh+acrOaYr+WQpuWMuemFjeWUpOmGkuivjSAnTm91cycgL25hyopzL+OAggogICAg6L+U5ZueIChpc193YWtlOiBib29sLCBncmVldGluZzogc3RyKSDigJQgZ3JlZXRpbmcg55So5LqOIEFwcCDpgInmi6npl67lgJnor63jgIIiIiIKICAgIGlmIG5vdCB0ZXh0IG9yIG5vdCB0ZXh0LnN0cmlwKCk6CiAgICAgICAgcmV0dXJuIChGYWxzZSwgIiIpCiAgICB0ID0gX3JlLnN1YihyIiIiW1xzLO+8jOOAgi4h77yBP++8n+OAgX4n4oCY4oCZIuKAnOKAnVwtX10iIiIsICcnLCB0ZXh0Lmxvd2VyKCkuc3RyaXAoKSkKICAgIGlmIG5vdCB0IG9yIGxlbih0KSA+IDIwOgogICAgICAgIHJldHVybiAoRmFsc2UsICIiKQogICAgIyAwKSDliY3nvIDmo4DmtYvvvJrlnKjlkJfihpIi5oiR5Zyo55qEIiAg5L2g5aW9L+WYv+KGkiLll6/vvIzmiJHlnKjvvIzor7for7QiCiAgICB6YWltYSA9IHsi5Zyo5ZCXIiwgIuWcqOS5iCIsICLlnKjll44iLCAi5Zyo5LiN5ZyoIiwgInphaW1hIn0KICAgIGhlbGxvID0geyLkvaDlpb0iLCAi5Zi/IiwgIuWXqCIsICJoaSIsICJoZWxsbyIsICLlk4jllr0iLCAi5ZOI5ZWwIiwgIum7kSJ9CiAgICBoYXNfemFpbWEgPSBhbnkocCBpbiB0IGZvciBwIGluIHphaW1hKQogICAgaGFzX2hlbGxvID0gKG5vdCBoYXNfemFpbWEpIGFuZCBhbnkocCBpbiB0IGZvciBwIGluIGhlbGxvKQogICAgIyDljrvmjonmnIDplb/ljLnphY3nmoTliY3nvIDvvIzlvpfliLDmoLjlv4PllKTphpLor43vvIgi5Zyo5ZCXTm91cyIg4oaSICJub3VzIu+8iQogICAgY29yZSA9IHQKICAgIGZvciBwIGluIHNvcnRlZCh6YWltYSB8IGhlbGxvLCBrZXk9bGVuLCByZXZlcnNlPVRydWUpOgogICAgICAgIGlmIHAgaW4gY29yZToKICAgICAgICAgICAgY29yZSA9IGNvcmUucmVwbGFjZShwLCAiIiwgMSkKICAgICAgICAgICAgYnJlYWsKICAgIGNvcmUgPSBjb3JlLnN0cmlwKCkKICAgICMgMSkg5pi+5byP6L+R6Z+z6K+N5bqTOiB3aGlzcGVyIOWwj+aooeWei+WvuSAvbmHKinMvIOeahOWQhOenjeiLseaWh+WGmeazlSArIOS4reaWh+WQjOmfswogICAgIyAgICDms6jmhI8gdC9jb3JlIOW3suWJpeemu+aSh+WPtyzmlYXor43lupPkuI3lkKvmkoflj7flj5jkvZMo55SoIG5vd3Mvbm9zIOetieimhueblikKICAgIGt3cyA9IFsKICAgICAgICAibm91cyIsICJub3VzZSIsICJub29zZSIsICJub29jZSIsICJub29zIiwgIm5vb3plIiwgIm5vb3oiLCAibnVzZSIsICJudXMiLCAibnVzcyIsCiAgICAgICAgIm5ld2NlIiwgIm5ld3MiLCAibmV3c2UiLCAia25vdXMiLCAia25hdXMiLCAibmF1cyIsICJuYXVzcyIsICJub3dzIiwgIm5vd2VzIiwgIm5vcyIsCiAgICAgICAgImtub3dzIiwgImduYXdzIiwgIm1vdXNzZSIsICJtb29zZSIsICJub3V4IiwgIm5veCIsICJub3JzIiwgIm5hd2VzIiwgIm5hb3MiLAogICAgICAgICJub3NlIiwgIm5vemUiLCAibm9heiIsICJub3V6IiwgIm5vc3MiLCAibm9lc2UiLCAibm91Y2UiLCAibm93c2UiLCAibmF3cyIsICJuYXdzcyIsCiAgICAgICAgImhvdXNlIiwgImhvd3MiLCAiaG93c2UiLCAiaGF1c2UiLCAiaGF1cyIsICJob3NzIiwgImhvdXMiLCAiaG91c3MiLCAiaG9lc2UiLCAiaG93emUiLAogICAgICAgICJsYW9zIiwgImxvdXNlIiwgImxvc3MiLCAibG93cyIsICJsb3dlcyIsCiAgICAgICAgIuivuuaWryIsICLliqrmlq8iLCAi57q95pavIiwgIumXueaWryIsICLmjKDmlq8iLCAi6ISR5pavIiwgIumXueS4nSIsICLor7rkuJ0iLCAi5Yqq5LidIiwgIuivuuWPuCIsICLliqrlj7giLAogICAgICAgICLpgqPmrKfmlq8iLCAi6ISR5biIIiwgIumXueW4iCIsICLmi7/mlq8iLCAi6YKj5pavIiwgIuezr+aWryIsICLor7ror7oiLCAi5Yqq6K+6IiwgIuivuuWKqiIsCiAgICAgICAgIuS9oOWlveivuiIsICLlsI/or7oiLCAi5Zi/6K+6IiwgIum7keivuiIsICLll6jor7oiLCAi5Zi/bm91cyIsICLll6hub3VzIiwgIuS9oOWlvW5vdXMiLAogICAgXQoKICAgIGRlZiBfbG9va3Mocyk6CiAgICAgICAgIiIi5LiA5q61KOWOu+WJjee8gOeahOaguOW/gyDmiJYg5a6M5pW05paH5pysKeaYr+WQpuWDj+WUpOmGkuivjSAvbmHKinMv44CCIiIiCiAgICAgICAgaWYgbm90IHM6CiAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIGlmIGFueShrdyBpbiBzIGZvciBrdyBpbiBrd3MpOgogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGlmIGxlbihzKSA8PSA1IGFuZCBhbnkoa3cgaW4gcyBmb3Iga3cgaW4gWyLpl7nmrbsiLCAi6ISR5q27IiwgIuiAgeaWryIsICLlirPmlq8iLCAi5o2e5pavIl0pOgogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGlmIGxlbihzKSA8PSA3IGFuZCBfcmUuZnVsbG1hdGNoKAogICAgICAgICAgICAgICAgciIoa258Z258bnxofGwpKG91fG9vfG93fGF1fG9hfGFvfGF3fG98dSkrKHN8enxzZXx6ZXxjZXxzc3xzaHx4fHp6KSIsIHMpOgogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGlmIF9yZS5mdWxsbWF0Y2gociIobnxrbnxnbikob3V8b3d8b298YXV8b2Epcz8iLCBzKToKICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAjIOWQjOaXtuWvueWujOaVtOaWh+acrOS4juWOu+WJjee8gOaguOW/g+WIpOWumijluKYi5Zyo5ZCXL+S9oOWlvSLliY3nvIDml7bmoLjlv4PmiY3mmK/llKTphpLor40pCiAgICB3YWtlID0gX2xvb2tzKHQpIG9yIF9sb29rcyhjb3JlKQogICAgaWYgbm90IHdha2U6CiAgICAgICAgcmV0dXJuIChGYWxzZSwgIiIpCiAgICAjIDMpIOmAieaLqemXruWAmeivrQogICAgaWYgaGFzX3phaW1hOgogICAgICAgIHJldHVybiAoVHJ1ZSwgIuaIkeWcqOeahCIpCiAgICBlbGlmIGhhc19oZWxsbzoKICAgICAgICByZXR1cm4gKFRydWUsICLll6/vvIzmiJHlnKjvvIzor7for7QiKQogICAgZWxzZToKICAgICAgICByZXR1cm4gKFRydWUsICLll6/vvIzor7for7QiKQo="
).decode("utf-8")

src, n1 = re.subn(
    r"def _is_wake_word\(text[^)]*\)[^:]*:.*?\n(?=\n\S|\ndef |\nclass )",
    lambda m: NEW_FUNC + "\n", src, count=1, flags=re.S)


# 2. wake_kw: language="en" → language=None, beam_size=5 → beam_size=1

src, n2 = re.subn(
    r'language="en"(?=, beam_size=\d+, temperature=0\.0)',
    'language=None', src, count=1)
src, n3 = re.subn(
    r'(language=None, )beam_size=\d+',
    r'\g<1>beam_size=1', src, count=1)
if n3 == 0:
    src, n3 = re.subn(
        r'beam_size=5(?=, temperature=0\.0)',
        'beam_size=1', src, count=1)


# 3. 更新 wake 处理块: 解包 (is_wake, greeting)

old_handle = (
    '        if hint == "wake":\n'
    '            is_wake = _is_wake_word(transcribe_text)\n'
    '            resp["wake"] = is_wake\n'
    '            log.info("唤醒检测: text=%r wake=%s", transcribe_text, is_wake)'
)
new_handle = (
    '        if hint == "wake":\n'
    '            is_wake, greeting = _is_wake_word(transcribe_text)\n'
    '            resp["wake"] = is_wake\n'
    '            resp["greeting"] = greeting\n'
    '            log.info("唤醒检测: text=%r wake=%s greeting=%s", transcribe_text, is_wake, greeting)'
)
if old_handle in src:
    src = src.replace(old_handle, new_handle, 1)
    n4 = 1
else:
    n4 = 0
    print("⚠ 未匹配到 wake 处理块,可能已被修改。")


# 校验 & 写回

if src == orig:
    print("未改动。n1=%d n2=%d n3=%d n4=%d" % (n1, n2, n3, n4))
    sys.exit(0)

ast.parse(src)
shutil.copyfile(path, path + ".bak3")
io.open(path, "w", encoding="utf-8").write(src)
print("✅ 已修补 %s (备份 .bak3)  函数=%d lang=%d beam=%d handle=%d" % (path, n1, n2, n3, n4))
