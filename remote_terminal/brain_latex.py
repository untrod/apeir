# -*- coding: utf-8 -*-
"""
LaTeX → 可读纯文本(后处理兜底)。
模型常无视"禁用 LaTeX"的提示仍输出 \\(...\\)、\\frac 等;手表/纯文本端不渲染会显示乱码原文。
这里在服务器侧统一转成可读 Unicode,任何端拿到的都是干净文本。

从 brain.py 提取,零外部依赖。
"""
import re as _re

_SUP = {"0":"⁰","1":"¹","2":"²","3":"³","4":"⁴","5":"⁵","6":"⁶","7":"⁷","8":"⁸","9":"⁹",
        "+":"⁺","-":"⁻","n":"ⁿ","i":"ⁱ","x":"ˣ","(":"⁽",")":"⁾"}
_SUB = {"0":"₀","1":"₁","2":"₂","3":"₃","4":"₄","5":"₅","6":"₆","7":"₇","8":"₈","9":"₉",
        "+":"₊","-":"₋","n":"ₙ","i":"ᵢ","x":"ₓ","(":"₍",")":"₎"}
_LATEX_SYM = {
    r"\times":"×", r"\cdot":"·", r"\div":"÷", r"\pm":"±", r"\mp":"∓",
    r"\leq":"≤", r"\geq":"≥", r"\neq":"≠", r"\approx":"≈", r"\equiv":"≡",
    r"\infty":"∞", r"\sum":"Σ", r"\int":"∫", r"\prod":"∏", r"\partial":"∂",
    r"\alpha":"α", r"\beta":"β", r"\gamma":"γ", r"\delta":"δ", r"\theta":"θ",
    r"\pi":"π", r"\lambda":"λ", r"\mu":"μ", r"\sigma":"σ", r"\omega":"ω",
    r"\Delta":"Δ", r"\Omega":"Ω", r"\rightarrow":"→", r"\to":"→", r"\Rightarrow":"⇒",
    r"\sin":"sin", r"\cos":"cos", r"\tan":"tan", r"\log":"log", r"\ln":"ln",
    r"\lim":"lim", r"\sqrt":"√", r"\left":"", r"\right":"", r"\,":" ", r"\;":" ",
    r"\quad":"  ", r"\!":"", r"\cdots":"…", r"\ldots":"…",
}

def _to_script(s, table):
    return "".join(table.get(ch, ch) for ch in s) if all(c in table for c in s) else None

def delatex(text):
    """将 LaTeX 数学公式转为可读纯文本。"""
    if not text or ("\\" not in text and "^" not in text and "_" not in text and "$" not in text):
        return text
    t = text
    # 分隔符
    t = t.replace(r"\[", " ").replace(r"\]", " ").replace(r"\(", "").replace(r"\)", "")
    t = t.replace("$$", "").replace("$", "")
    # \frac{a}{b} -> (a)/(b)
    frac = _re.compile(r"\\frac\{([^{}]*)\}\{([^{}]*)\}")
    prev = None
    while prev != t:
        prev = t
        t = frac.sub(lambda m: f"({m.group(1)})/({m.group(2)})", t)
    # \sqrt{x} -> √(x)
    t = _re.sub(r"\\sqrt\{([^{}]*)\}", lambda m: f"√({m.group(1)})", t)
    # 上下标
    def _sup_brace(m):
        r = _to_script(m.group(1), _SUP); return r if r else f"^({m.group(1)})"
    def _sub_brace(m):
        r = _to_script(m.group(1), _SUB); return r if r else f"_({m.group(1)})"
    t = _re.sub(r"\^\{([^{}]*)\}", _sup_brace, t)
    t = _re.sub(r"\^([A-Za-z0-9])", lambda m: _SUP.get(m.group(1), f"^{m.group(1)}"), t)
    t = _re.sub(r"_\{([^{}]*)\}", _sub_brace, t)
    t = _re.sub(r"_([A-Za-z0-9])", lambda m: _SUB.get(m.group(1), f"_{m.group(1)}"), t)
    # 命令符号
    for k, v in _LATEX_SYM.items():
        t = t.replace(k, v)
    return t
