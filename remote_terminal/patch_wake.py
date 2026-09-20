#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原地修补 brain.py:替换 _is_wake_word(近音词库+模糊音规则) + 唤醒段自动检测语言。
   用法: python3 patch_wake.py /opt/nous/brain.py   (幂等,先备份 .bak)"""
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

# _is_wake_word 最终版(base64 内嵌,避免转义出错)
NEW_FUNC = base64.b64decode(
    "ZGVmIF9pc193YWtlX3dvcmQodGV4dDogc3RyKSAtPiBib29sOgogICAgIiIi5qOA5p+l6L2s5YaZ5paH5pys5piv5ZCm5Yy56YWN5ZSk6YaS6K+NICdOb3VzJyAvbmHKinMv44CCCiAgICDnrZbnlaU65pi+5byP6L+R6Z+z6K+N5bqTICsg5qih57OK6Z+z6KeE5YiZKOmVv+W+l+WDjyAvbmHKinMvIOWwseeulyks5YW86aG+5Y+s5Zue5LiO6K+v6Kem5Y+R44CCIiIiCiAgICBpZiBub3QgdGV4dCBvciBub3QgdGV4dC5zdHJpcCgpOgogICAgICAgIHJldHVybiBGYWxzZQogICAgdCA9IF9yZS5zdWIociJbXHMs77yM44CCLiHvvIE/77yf44CBficn4oCY4oCZXCJcLV9dIiwgJycsIHRleHQubG93ZXIoKS5zdHJpcCgpKQogICAgaWYgbm90IHQgb3IgbGVuKHQpID4gMTQ6CiAgICAgICAgcmV0dXJuIEZhbHNlICAjIOWUpOmGkuivjeW+iOefrTvplb/lj6XkuI3mmK8KICAgICMgMSkg5pi+5byP6L+R6Z+z6K+N5bqTOndoaXNwZXIg5bCP5qih5Z6L5a+5IC9uYcqKcy8g55qE5ZCE56eN6Iux5paH5YaZ5rOVICsg5Lit5paH5ZCM6Z+zCiAgICBrd3MgPSBbCiAgICAgICAgIyDigJTigJQg6Iux5paH5Y+K6L+R6Z+zIOKAlOKAlAogICAgICAgICJub3VzIiwgIm5vdXNlIiwgIm5vb3NlIiwgIm5vb2NlIiwgIm5vb3MiLCAibm9vemUiLCAibm9veiIsICJudXNlIiwgIm51cyIsICJudXNzIiwKICAgICAgICAibmV3Y2UiLCAibmV3cyIsICJuZXdzZSIsICJrbm91cyIsICJrbmF1cyIsICJuYXVzIiwgIm5hdXNzIiwgIm5vd3MiLCAibm93ZXMiLCAibm93J3MiLAogICAgICAgICJudSdzIiwgIm5vJ3MiLCAia25vd3MiLCAiZ25hd3MiLCAibW91c3NlIiwgIm1vb3NlIiwgIm5vdXgiLCAibm94IiwgIm5vcnMiLCAibmF3ZXMiLAogICAgICAgICJub3NlIiwgIm5vemUiLCAibm9heiIsICJub3V6IiwgIm5vc3MiLCAibm9lc2UiLCAibm91Y2UiLCAibm93c2UiLCAibmF3cyIsICJuYXdzcyIsCiAgICAgICAgImhvdXNlIiwgImhvd3MiLCAiaG93c2UiLCAiaGF1c2UiLCAiaGF1cyIsICJob3NzIiwgImhvdXMiLCAiaG91c3MiLCAiaG9lc2UiLCAiaG93emUiLAogICAgICAgICJsYW8ncyIsICJsb3VzZSIsICJsb3NzIiwgImxvd3MiLCAibG93ZXMiLAogICAgICAgICMg4oCU4oCUIOS4reaWh+WPiui/kemfsyjlv7XmiJAi6Ze55q27L+mXueaWry/pgqPmrKfmlq8i562JKeKAlOKAlAogICAgICAgICLor7rmlq8iLCAi5Yqq5pavIiwgIue6veaWryIsICLpl7nmlq8iLCAi5oyg5pavIiwgIuiEkeaWryIsICLpl7nkuJ0iLCAi6K+65LidIiwgIuWKquS4nSIsICLor7rlj7giLCAi5Yqq5Y+4IiwKICAgICAgICAi6YKj5qyn5pavIiwgIuiEkeW4iCIsICLpl7nluIgiLCAi5ou/5pavIiwgIumCo+aWryIsICLns6/mlq8iLAogICAgICAgICLor7ror7oiLCAi5Yqq6K+6IiwgIuivuuWKqiIsCiAgICAgICAgIuS9oOWlveivuiIsICLlsI/or7oiLCAi5Zi/6K+6IiwgIum7keivuiIsICLll6jor7oiLCAi5Zi/bm91cyIsICLll6hub3VzIiwgIuS9oOWlvW5vdXMiLAogICAgXQogICAgaWYgYW55KGt3IGluIHQgZm9yIGt3IGluIGt3cyk6CiAgICAgICAgcmV0dXJuIFRydWUKICAgICMg5LiO5bi46KeB6K+N6YeN5Y+g55qE5ZCM6Z+zKOmXueatuy/ohJHmrbsv6ICB5pav4oCmKTrku4XlvZPmlbTmrrXlvojnn60o5Y2V5b+15ZSk6YaS6K+NKeaJjeeulyzpgb/lhY3plb/lj6Xor6/op6YKICAgIGlmIGxlbih0KSA8PSA1IGFuZCBhbnkoa3cgaW4gdCBmb3Iga3cgaW4gWyLpl7nmrbsiLCAi6ISR5q27IiwgIuiAgeaWryIsICLlirPmlq8iLCAi5o2e5pavIiwgIumXueS4nSIsICLohJHmlq8iXSk6CiAgICAgICAgcmV0dXJuIFRydWUKICAgICMgMikg5qih57OK6Z+z6KeE5YiZOm4vaC9rbi9nbiDotbfmiYsgKyDlkI7lhYPpn7Moby9vdS9vdy9vby9hdeKApikrIHMveiDnsbvmlLblsL4g4oaSIOWIpOS4uuWUpOmGkgogICAgIyAgICDopoHmsYLmnInmlLblsL7ovoXpn7Ms5o6S6ZmkICJuby9ub3cvaG93IiDnrYk75YWD6Z+z6ZmQ5ZCO5YWD6Z+zLOaOkumZpCAiaGFzL25pY2UiIOetiQogICAgaWYgbGVuKHQpIDw9IDcgYW5kIF9yZS5mdWxsbWF0Y2goCiAgICAgICAgICAgIHIiKGtufGdufG58aHxsKShvdXxvb3xvd3xhdXxvYXxhb3xhd3xvfHUpKyhzfHp8c2V8emV8Y2V8c3N8c2h8eHx6enxzJ3MpIiwgdCk6CiAgICAgICAgcmV0dXJuIFRydWUKICAgICMg6LW35omL5bCx5pivIG5vdXMg55qEIum8u+mfsyvlkI7lhYPpn7MiKG5vdy9ub3Uvbm9vL25hdeKApik65Y2z5L6/57uT5bC+IHMg5rKh5ZCs5riF5Lmf566XCiAgICBpZiBfcmUuZnVsbG1hdGNoKHIiKG58a258Z24pKG91fG93fG9vfGF1fG9hKXM/IiwgdCk6CiAgICAgICAgcmV0dXJuIFRydWUKICAgIHJldHVybiBGYWxzZQo="
).decode("utf-8")

# 1. 整段替换 _is_wake_word(兼容有/无类型注解)
src, n1 = re.subn(r"def _is_wake_word\(text[^)]*\)[^:]*:.*?\n(?=\n\S|\ndef |\nclass )",
                  lambda m: NEW_FUNC + "\n", src, count=1, flags=re.S)
# 2a. 去掉唤醒偏置 prompt
src, n2 = re.subn(r'prompt\s*=\s*"[^"]*Nous[^"]*"\s*if\s*hint\s*==\s*"wake"\s*else\s*None',
                  lambda m: "prompt = None", src)
# 2b. transcribe 的 language="zh" → 唤醒自动检测、命令仍中文
src, n3 = re.subn(r'language\s*=\s*"zh"',
                  lambda m: 'language=(None if hint == "wake" else "zh")', src, count=1)

if src == orig:
    print("未改动(可能已是最新)。n1=%d n2=%d n3=%d" % (n1, n2, n3))
    sys.exit(0)
ast.parse(src)  # 语法自检,不过不写
shutil.copyfile(path, path + ".bak")
io.open(path, "w", encoding="utf-8").write(src)
print("已修补 %s (备份 .bak)  词库=%d prompt=%d language=%d" % (path, n1, n2, n3))
