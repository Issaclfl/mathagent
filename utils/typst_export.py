"""Markdown → Typst 转换器（实用子集）。

把 Writer 生成的 Markdown 论文转换为 Typst 源文件（.typ），可配合 typst CLI
编译成 PDF（竞赛提交格式）。转换子集覆盖本项目的论文结构：
标题层级 / 段落 / 表格 / LaTeX 公式 / 列表 / 代码块 / 分隔线 / 加粗斜体 / 图片。

用法：
  from utils.typst_export import md_to_typst
  typ = md_to_typst(markdown_text)
"""
from __future__ import annotations

import re


def _heading(level: int, text: str) -> str:
    """Markdown # 标题 → Typst = 标题。"""
    return "=" * level + " " + text.strip()


def _table_to_typst(rows: list[list[str]], caption: str = "") -> str:
    """Markdown 表格行 → Typst 三线表（国赛规范：顶线/表头下线/底线，无侧边框）。

    表题作为段落输出在表格上方（国赛规范），不走 figure caption。
    有表题 → 表题段落 + #align(center, table(...))
    无表题（如符号说明表）→ #align(center, table(...))
    """
    ncols = max(len(r) for r in rows) if rows else 0
    parts = [
        "  table(",
        f"    columns: {ncols},",
        "    stroke: none,",
        "    inset: (x: 0.8em, y: 0.5em),",
        "    table.hline(stroke: 1.5pt),  // 顶线",
    ]
    for i, row in enumerate(rows):
        cells = [_inline(c.strip()) for c in row]
        if i == 0:
            parts.extend(f"    [*{c}*]," for c in cells)
            parts.append("    table.hline(stroke: 0.5pt),  // 表头下线")
        else:
            parts.extend(f"    [{c}]," for c in cells)
    parts.append("    table.hline(stroke: 1.5pt),  // 底线")
    parts.append("  )")
    table_code = "#align(center,\n" + "\n".join(parts) + "\n)"
    # 表题放在表格上方（段落形式，居中，加粗）
    if caption:
        result = f"*{caption}*\n{table_code}"
    else:
        result = table_code
    # DEBUG
    if '==============' in result:
        print(f"[BUG] _table_to_typst 返回了 ====== 行！")
        print(f"  第一行: {repr(result.split(chr(10))[0][:50])}")
    return result


def _math_convert(text: str) -> str:
    r"""LaTeX 数学子集 → Typst 数学（覆盖建模论文常见命令）。

    不追求完整转换——未知命令原样保留（Typst 报错时人工修正），
    覆盖高频：\text/\frac/\left\right/\sum/\prod/\mathbb/\mathcal/
    \operatorname/\quad/\tag/希腊字母/关系符等。
    """
    # 1. \text{...} → "..."（Typst 字符串）
    text = re.sub(r"\\text\{([^{}]*)\}", r'"\1"', text)
    # 2. \frac{a}{b} → (a)/(b)（手动扫描两个花括号参数并整体消费）
    def _frac_parse(s: str, start: int):
        """从 start 处（\\frac 之后）解析 {a}{b}，返回 (替换串, 参数结束位置)。"""
        depth, j = 0, start
        while j < len(s):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        a = s[start + 1:j]
        depth, k = 0, j + 1
        while k < len(s):
            if s[k] == "{":
                depth += 1
            elif s[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        b = s[j + 2:k]
        return f"({_math_convert(a)})/({_math_convert(b)})", k + 1

    _out, _i = [], 0
    while _i < len(text):
        if text.startswith("\\frac", _i):
            repl, _i = _frac_parse(text, _i + 5)
            _out.append(repl)
        else:
            _out.append(text[_i])
            _i += 1
    text = "".join(_out)
    # 3. 删除无意义命令
    text = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg|quad|qquad|quad)\b", "", text)
    text = re.sub(r"\\(?:left|right)\.", "", text)  # \left. \right.
    text = re.sub(r"\\,|\\;|\\!", "", text)
    # 环境标记（cases/array）删除命令保留内容结构
    text = re.sub(r"\\(?:begin|end)\{[a-zA-Z*]*\}", "", text)
    # LaTeX 数学换行 \\[2mm] → Typst \（行尾换行）
    text = re.sub(r"\\\\(\[[^\]]*\])?", " \\\\ ", text)
    # 4. \mathbb{X} → bb(X)；\mathcal{X} → cal(X)；\mathrm{X} → X
    text = re.sub(r"\\mathbb\{([^{}]*)\}", r"bb(\1)", text)
    text = re.sub(r"\\mathcal\{([^{}]*)\}", r"cal(\1)", text)
    text = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\operatorname\{([^{}]*)\}", r'op("\1")', text)
    # 微分书写：dH/dt → d H / d t（Typst 数学模式多字母标识符会报 unknown variable）
    text = re.sub(r"(?<![A-Za-z])d([A-Za-z])(?![A-Za-z])", r"d \1", text)
    # 5. 上下限：\sum_{a}^{b} → sum_(a)^(b)（配平扫描花括号，支持嵌套如 E_{RH}）
    _LIMIT_NAMES = {"sum": "sum", "prod": "product", "int": "integral",
                    "max": "max", "min": "min"}

    def _limits(text):
        out = []
        i = 0
        while i < len(text):
            m = re.match(r"\\(sum|prod|int|max|min)", text[i:])
            if not m:
                out.append(text[i])
                i += 1
                continue
            name = _LIMIT_NAMES.get(m.group(1), m.group(1))
            j = i + m.end()
            parts = []
            while j < len(text) and text[j] in "_^":
                op = text[j]
                if j + 1 < len(text) and text[j + 1] == "{":
                    depth, k = 0, j + 1
                    while k < len(text):
                        if text[k] == "{":
                            depth += 1
                        elif text[k] == "}":
                            depth -= 1
                            if depth == 0:
                                break
                        k += 1
                    content = text[j + 2:k]
                    parts.append(f"{op}({_math_convert(content)})")
                    j = k + 1
                elif j + 1 < len(text) and (text[j + 1].isalnum()):
                    parts.append(f"{op}({text[j + 1]})")
                    j += 2
                else:
                    break
            out.append(name + "".join(parts))
            i = j
        return "".join(out)
    text = _limits(text)
    # 6. 带花括号参数的函数命令 → 括号调用：\hat{x} → hat(x)
    # 无花括号形式先转花括号：\hat D_i → \hat{D_i}
    for _cmd in (r"\hat", r"\bar", r"\tilde", r"\vec"):
        text = re.sub(
            re.escape(_cmd) + r"\s+([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)",
            lambda m, c=_cmd: c + "{" + m.group(1) + "}",
            text,
        )
    for _cmd, _fn in ((r"\hat", "hat"), (r"\bar", "overline"),
                      (r"\tilde", "tilde"), (r"\sqrt", "sqrt"),
                      (r"\vec", "arrow")):
        # 手动扫描并消费完整 {参数}（re.sub 只替换命令本身，参数会残留）
        _out, _i = [], 0
        while _i < len(text):
            if text.startswith(_cmd, _i):
                rest = text[_i + len(_cmd):]
                if rest.startswith("{"):
                    depth, j = 0, 0
                    while j < len(rest):
                        if rest[j] == "{":
                            depth += 1
                        elif rest[j] == "}":
                            depth -= 1
                            if depth == 0:
                                break
                        j += 1
                    content = rest[1:j]
                    _out.append(_fn + "(" + _math_convert(content) + ")")
                    _i += len(_cmd) + j + 1
                else:
                    _out.append(text[_i])
                    _i += 1
            else:
                _out.append(text[_i])
                _i += 1
        text = "".join(_out)
    # 6b. 常用命令映射（二元操作符两侧加空格，防止与相邻符号粘连）
    # \top 先单独处理（避免被 \to 规则误伤成 " -> p"）
    text = text.replace(r"\top", "top")
    _MAP = {
        r"\forall": "forall", r"\exists": "exists", r"\infty": "oo",
        r"\nabla": "gradient", r"\partial": "diff", r"\sim": "~",
        r"\approx": "approx", r"\propto": "prop", r"\dots": "dots",
        r"\ldots": "dots", r"\emptyset": "empty", r"\varnothing": "empty",
        r"\hat": "hat", r"\bar": "overline", r"\tilde": "tilde",
        r"\vec": "arrow", r"\sqrt": "sqrt", r"\exp": "exp",
        r"\log": "log", r"\ln": "ln", r"\sin": "sin", r"\cos": "cos",
        r"\tan": "tan", r"\min": "min", r"\max": "max",
        r"\alpha": "alpha", r"\beta": "beta", r"\gamma": "gamma",
        r"\Gamma": "Gamma", r"\delta": "delta", r"\Delta": "Delta",
        r"\epsilon": "epsilon", r"\varepsilon": "epsilon",
        r"\theta": "theta", r"\Theta": "Theta", r"\lambda": "lambda",
        r"\mu": "mu", r"\pi": "pi", r"\Pi": "Pi", r"\rho": "rho",
        r"\sigma": "sigma", r"\Sigma": "Sigma", r"\tau": "tau",
        r"\phi": "phi", r"\Phi": "Phi", r"\varphi": "phi",
        r"\omega": "omega", r"\Omega": "Omega", r"\xi": "xi",
        r"\zeta": "zeta", r"\eta": "eta", r"\kappa": "kappa",
        r"\nu": "nu", r"\psi": "psi", r"\chi": "chi",
        r"\{": "\{", r"\}": "\}",
    }
    _BINOP = {
        r"\cdot": " dot ", r"\times": " times ", r"\pm": " plus.minus ",
        r"\in": " in ", r"\notin": " not.in ", r"\subset": " subset ",
        r"\to": " -> ", r"\rightarrow": " -> ", r"\Rightarrow": " => ",
        r"\cup": " union ", r"\cap": " sect ", r"\bigcup": " union ", r"\bigcap": " sect ",
        r"\le": " <= ", r"\ge": " >= ", r"\ne": " != ", r"\neq": " != ",
    }
    text = text.replace(r"\|", "|")  # 范数 \|x\| → |x|
    for k, v in _BINOP.items():
        text = text.replace(k, v)
    for k, v in _MAP.items():
        # 前导空格：\boldsymbol\theta → \boldsymbol theta，防命令与变量粘连
        # 成 \boldsymboltheta 被兜底整体误删
        text = text.replace(k, " " + v)
    # 6b1b. % 在 Typst math 模式是注释符 → 需要引号化
    #   已转义的 \%（LaTeX 百分号）保留——typst 数学里 \% 是合法转义
    text = re.sub(r'(?<![\\"])%(?!")', '"%"', text)
    # 6b1c. Typst 保留字引号化（lambda/max/min 等在 math 模式需要引号）
    _RESERVED = {"lambda", "max", "min", "sin", "cos", "tan", "log", "ln", "exp",
                 "sum", "product", "integral", "inf", "sup", "lim", "mod"}
    def _quote_reserved(m):
        word = m.group(0)
        return '"' + word + '"' if word in _RESERVED else word
    text = re.sub(r'\b([a-zA-Z]+)\b', _quote_reserved, text)
    # 6b1d. 清理前导空格（$ sigma$ → $sigma$）
    text = text.strip()
    # 6b1.5. 角度符号：^\circ / \circ → °
    #    必须早于 6b2 兜底删命令——否则 \circ 被删掉只剩 "0^"，
    #    Typst 空上标直接报错（实测 $0^\circ$ → $0^$）
    text = re.sub(r"\^?\\circ\b", "°", text)
    # 6b2. 兜底：未映射的 LaTeX 命令删除命令、保留花括号内容
    #    （\boldsymbol{theta} → theta；\mathbf{x} → x）；
    #    迭代处理嵌套命令参数（\hat{\boldsymbol{theta}} → theta）。
    #    必须在引号化之前——否则 \boldsymbol 会被当成多字母变量引号化错乱
    for _ in range(3):
        new = re.sub(
            r"\\[a-zA-Z]+\{([^{}]*)\}",
            lambda m: m.group(1),
            text,
        )
        if new == text:
            break
        text = new
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    # 6b3. 裸上标/下标花括号多字母引号化：^{delivered} → ^("delivered")。
    #    在兜底删命令之后执行（^{\top} 先删 \ 变 ^{top} 再引号化，避免 \ 残留）；
    #    含引号的组跳过（f_{"inf"} 来自 \text 转换，二次引号化会错乱）。
    #    但已引号化的组必须先剥花括号：_{"cov"} → _("cov")——否则 Typst 报
    #    unexpected underscore（_{ 不是合法语法，实测 t_{\text{cov}} 转换后残留）
    text = re.sub(r"\_\{(\"[^\"]*\")\}", r"_(\1)", text)
    text = re.sub(r"\^\{(\"[^\"]*\")\}", r"^(\1)", text)
    # 逗号混合组：_{"start",k} → _("start", k)（Typst 多下标语法，剥花括号）
    text = re.sub(r"\_\{(\"[^\"]*\")\s*,\s*([^{}]*)\}", r"_(\1, \2)", text)
    text = re.sub(r"\^\{(\"[^\"]*\")\s*,\s*([^{}]*)\}", r"^(\1, \2)", text)
    # 数学模式：_ / ^ 前多余空格删除（LaTeX 命令删除后遗留的空格会让 Typst
    # 把前缀下标/上标当文本解析，报 unexpected underscore）
    text = re.sub(r"\s+([_^])", r"\1", text)
    _SUP_PAT = "\\^\\{([^{}\\\"']*)\\}"
    _SUB_PAT = "\\_\\{([^{}\\\"']*)\\}"

    def _fmt_group(group: str, is_sub: bool = True) -> str:
        """Typst 上/下标花括号内容格式化。

        含逗号 → Typst 多下标分组语法 _(i, 0) / ^(i, 0)
        纯字母多字符 → Typst 引号语法 _（"i"）/ ^（"i"）
        多数字 → 括号分组语法 _(12)（不引号）
        单字符或其他 → 保持原样
        """
        group = group.strip()
        prefix = "^(" if not is_sub else "_("
        # 逗号分隔 → Typst 分组：_(i, 0)（数字不引号，字母不引号，仅多字母混合引号）
        if "," in group:
            parts = [p.strip() for p in group.split(",")]
            formatted = []
            for p in parts:
                # 纯数字、纯字母标识符保留原样；仅多字母/特殊内容加引号
                if re.fullmatch(r"\d+|[A-Za-z][A-Za-z0-9_]*", p) and not (re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", p) and len(p) > 1):
                    formatted.append(p)
                else:
                    formatted.append('"' + p + '"')
            return prefix + ", ".join(formatted) + ")"
        # 多字符组（长度 >1）：纯数字用括号，纯字母/混合用引号
        if len(group) > 1:
            if re.fullmatch(r"\d+", group):
                return prefix + group + ")"
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", group):
                return prefix + '"' + group + '")'
            return prefix + '"' + group + '")'
        # 单字符：直接（不引号，不括号）
        return "^" + group if not is_sub else "_" + group

    text = re.sub(_SUP_PAT, lambda m: _fmt_group(m.group(1), is_sub=False), text)
    text = re.sub(_SUB_PAT, lambda m: _fmt_group(m.group(1), is_sub=True), text)
    # 6c. 顶层多字母标识符引号化（Typst 数学未定义变量会报错）：
    #     delivered → "delivered"；内置词（alpha/sum/hat 等）保留
    _TYPST_WORDS = (
        set(_MAP.values()) | set(_BINOP.values())
        | {"sum", "product", "integral", "max", "min", "d", "e", "op", "bb", "cal",
           "plus", "minus", "dot", "times"}  # plus.minus 等符号词的分段（\pm 映射）
        # Typst 标记/表格/图片关键字（不应被引号化）
        | {"align", "center", "table", "stroke", "none", "inset", "columns",
           "hline", "figure", "image", "caption", "kind", "type", "width", "height",
           "size", "font", "text", "set", "show", "page", "math", "equation",
           "numbering", "em", "pt", "px", "cm", "mm", "m", "kw", "kWh"}
    )

    def _quote_var(m):
        w = m.group(0)
        return w if w in _TYPST_WORDS else '"' + w + '"'

    # 保护已引号内容（"drain" 等）：整体替换为占位符，避免内部字母被二次引号化
    _quoted: list[str] = []

    def _protect(m):
        _quoted.append(m.group(0))
        return f"\x00{len(_quoted) - 1}\x00"

    text = re.sub(r'"[^"]*"', _protect, text)
    text = re.sub(r"[A-Za-z]{2,}", _quote_var, text)
    for _qi, _q in enumerate(_quoted):
        text = text.replace(f"\x00{_qi}\x00", _q)
    # 7. \tag{n} 删除（公式编号由正文结构提供）
    text = re.sub(r"\\tag\{[^{}]*\}", "", text)
    # 裸上下标后紧跟字母时加空格：x^That → x^T hat（防 Typst 连写解析为单变量）
    text = re.sub(r"(\^|_)([A-Za-z0-9])(?=[A-Za-z])", r"\1\2 ", text)
    # LaTeX 行内空格 \ → Typst 空格（Typst 中 \ 是换行，但 LaTeX \ 是行内空格）
    # 排除已转换的 \\（换行），仅替换单反斜杠+空格
    text = re.sub(r"(?<!\\)\\ ", " ", text)
    return text


def _inline(text: str) -> str:
    """行内标记转换：加粗/斜体/行内公式/特殊字符。"""
    # 加粗保护（避免被斜体规则二次处理）
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: "\x00B" + m.group(1) + "\x00B", text)
    # 斜体 *it* → _it_
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"_\1_", text)
    # 剩余星号（残缺 Markdown，如 *Dijkstra/A**）转义为字面量
    text = re.sub(r"\*", r"\\*", text)
    text = text.replace("\x00B", "*")  # 恢复加粗 → *b*（Typst 原生加粗）
    # \(x\) → $x$（LaTeX 数学转 Typst；内容可含 ) 等字符）
    def _math_inline(m):
        return "$" + _math_convert(m.group(1)) + "$"
    text = re.sub(r"\\\((.+?)\\\)", _math_inline, text)
    # $x$ 行内公式（MathJax 风格，LLM 常用）同样转换
    text = re.sub(r"\$([^$\n]+?)\$", lambda m: "$" + _math_convert(m.group(1)) + "$", text)
    # 文本中的 LaTeX 下标/上标残留：LLM 常在正文写 t_{d(i+1)} / 5^3，
    # Typst 文本模式 { } 有分组语义、_ / ^ 触发数学上下标，直接编译报错。
    # 转义为字面量：t_{d(i+1)} → t\_(d(i+1))，^ 同理
    text = re.sub(r"_\{([^{}]+)\}", r"\\_(\1)", text)
    text = re.sub(r"\^\{([^{}]+)\}", r"\\^(\1)", text)
    # 文本模式转义：< 是 Typst label 语法（涉水深度<30cm 会报 unclosed label）。
    # 跳过 $...$ 公式段（数学模式 < 是关系符，转义会报错）
    parts = re.split(r"(\$[^$]*\$)", text)
    for _pi, _p in enumerate(parts):
        if _p.startswith("$") and _p.endswith("$"):
            continue
        parts[_pi] = _p.replace("<", "\\<")
    text = "".join(parts)
    text = text.replace("~", "\\~")  # Typst 波浪号转义（避免上标语义）
    return text


def _emit_eq(content: str, eq_counter: list[int]) -> str:
    """输出独立公式块；含 \\tag{n} 的公式启用 Typst 自动编号。

    Typst 编号：公式块末尾加 <eqN> label + 顶部 #set math.equation(numbering)。
    转换前提取 tag（转换后 tag 会被兜底规则吞掉）。
    """
    tag_m = re.search(r"\\tag\{([^{}]*)\}", content)
    content = re.sub(r"\\tag\{[^{}]*\}", "", content)
    body = _math_convert(content)
    if tag_m:
        eq_counter[0] += 1
        return f"$ {body} $ <eq{eq_counter[0]}>"  # label 在公式块外（Typst 编号语法）
    return f"$ {body} $"


def md_to_typst(md: str) -> str:
    """转换 Markdown 文本为 Typst 源文本（独立公式块自动编号）。"""
    eq_counter = [0]  # 公式编号计数器（带 tag 的公式才编号）
    in_abstract = False  # 摘要结束后在下一个 ## 标题前插入分页
    # CUMCM 国赛论文模板：页边距/字体/行距/页码 + 标题层级样式
    header = (
        "// === CUMCM 国赛论文模板 ===\n"
        "#set text(font: (\"SimSun\", \"KaiTi\"), size: 12pt) // 正文：小四号宋体\n"
        "#set par(leading: 0.8em) // 单倍行距\n"
        "#set page(margin: 2.5cm, numbering: \"1\") // 页边距 2.5cm，页码从 1 开始\n"
        "#set math.equation(numbering: \"(1)\")\n"
        "#set figure(numbering: none)\n"
        "// 标题样式：题目三号黑体居中，一级标题四号黑体居中，二三级小四黑体\n"
        "#show heading.where(level: 1): set text(font: \"SimHei\", size: 16pt)\n"
        "#show heading.where(level: 1): set align(center)\n"
        "#show heading.where(level: 2): set text(font: \"SimHei\", size: 14pt)\n"
        "#show heading.where(level: 2): set align(center)\n"
        "#show heading.where(level: 3): set text(font: \"SimHei\", size: 12pt)\n"
        "#show heading.where(level: 4): set text(font: \"SimHei\", size: 12pt)"
    )
    out: list[str] = [header]
    lines = md.splitlines()
    i = 0
    n = len(lines)
    in_code = False

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 代码块：原样保留
        if stripped.startswith("```"):
            out.append(line)
            in_code = not in_code
            i += 1
            continue
        if in_code:
            out.append(line)
            i += 1
            continue

        # 分隔线：国赛规范无分隔线（摘要后已有 pagebreak，其余位置不输出）
        if stripped == "---":
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            _t = _inline(m.group(2))
            # 参考文献单独一页（国赛规范：文末另起页）
            if "参考文献" in _t and m.group(1) == "##":
                out.append("#pagebreak()")
            # 摘要后第一个一级标题前自动分页（国赛规范：摘要+关键词独占一页，正文从新页开始）
            if "摘要" in _t and m.group(1) == "##":
                in_abstract = True
            elif in_abstract and m.group(1) == "##":
                out.append("#pagebreak()")
                in_abstract = False
            heading_line = _heading(len(m.group(1)), _t)
            out.append(heading_line)
            i += 1
            continue

        # 表格：| 行 + 下一行是 |---| 分隔行
        if stripped.startswith("|") and i + 1 < n:
            j = i
            rows: list[list[str]] = []
            is_table = False
            while j < n and lines[j].strip().startswith("|"):
                # 转义竖线 \|（LaTeX 范数）不作为单元格分隔
                cells = [c for c in re.split(r"(?<!\\)\|", lines[j].strip().strip("|"))]
                if j == i + 1 and all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in cells):
                    is_table = True  # 分隔行，跳过
                elif is_table or j == i:
                    rows.append(cells)
                j += 1
            if is_table:
                # 表题：表格上方（可跳过空行）的 "表N xxx" 文本行 → figure caption。
                # caption 只保留标题正文，表号交给 Typst 自动编号（表 1: xxx）。
                caption = ""
                k = i - 1
                while k > 0 and not lines[k].strip():
                    k -= 1
                prev = lines[k].strip() if k > 0 else ""
                m_cap = re.match(r"^\*{0,2}(表\s*\d+[^\n]{0,60})\*{0,2}$", prev)
                if m_cap and "|" not in prev and not prev.startswith("#"):
                    # 表号保留在 caption 文本中（表1/表6-1），与正文引用一致
                    caption = _inline(m_cap.group(1).rstrip("*"))
                    # 移除已输出的粗体表题行（及其后的空行），避免双标题
                    if out and out[-1] == "":
                        out.pop()
                    if out and out[-1].strip() == _inline(prev).strip():
                        out.pop()
                out.append(_table_to_typst(rows, caption))
                out.append("")
                i = j
                continue

        # 独立公式块（多行）：
        #   $$            \[
        #   ...     或    ...
        #   $$            \]
        if stripped == "$$" or stripped == r"\[":
            end_marker = "$$" if stripped == "$$" else r"\]"
            j = i + 1
            buf: list[str] = []
            while j < n and lines[j].strip() != end_marker:
                buf.append(lines[j])
                j += 1
            if j < n:  # 找到结束标记
                out.append(_emit_eq("\n".join(buf).strip(), eq_counter))
                out.append("")
                i = j + 1
                continue

        # 独立公式块（单行）$$...$$ 或 \[...\]
        if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
            out.append(_emit_eq(stripped[2:-2].strip(), eq_counter))
            i += 1
            continue
        if stripped.startswith(r"\[") and stripped.endswith(r"\]"):
            out.append(_emit_eq(stripped[2:-2].strip(), eq_counter))
            i += 1
            continue

        # 列表：- item 保留；N. item → 显式编号文本；* item → -（LLM 常用
        # 星号做无序列表项，Typst 里 * 是强调标记，不转会 unclosed delimiter）
        # 注意：Typst 的 `+` 有序列表遇空行会被拆成多个独立列表、编号重置为 1
        # （模型假设 8 项全变 "1."）。因此数字列表直接输出源数字文本（md 源编号连续）。
        m = re.match(r"^(\s*)(-|\*|\d+\.)\s+(.*)$", line)
        if m:
            marker = "-" if m.group(2) in ("-", "*") else m.group(2)
            if marker == "-":
                out.append(f"{m.group(1)}- {_inline(m.group(3))}")
            else:
                out.append(f"{m.group(1)}{marker} {_inline(m.group(3))}")
            i += 1
            continue

        # 图片
        m = re.match(r"^!\[(.*?)\]\((.*?)\)\s*$", line)
        if m:
            alt, path = m.group(1), m.group(2)
            # 图号保留在 caption 文本中（图1/图2/图3），与正文引用一致
            out.append(
                f"#figure(image(\"{path}\", width: 85%), caption: [{_inline(alt)}], kind: image)"
            )
            i += 1
            continue

        # 普通行（含空行）
        if stripped:
            _out_line = _inline(line)
            # 参考文献条目：加 <refN> label（跳转锚点），不转引用为超链接
            m_ref = re.match(r"^\[(\d+)\]", stripped)
            if m_ref:
                _out_line = f"<ref{m_ref.group(1)}> " + _out_line
                _out_line = "#v(0.4em)\n" + _out_line
            else:
                # 正文引用 [N] → 上标（国赛规范：引用标注用上标方括号）
                _out_line = re.sub(
                    r'(?<!\[)\[(\d+)\](?!\])',
                    r'#super([\1])',
                    _out_line,
                )
                # 参考文献条目（行首 [N]）增加间距
                if re.match(r"^\[\d+\]", stripped):
                    _out_line = "#v(0.4em)\n" + _out_line
            out.append(_out_line)
        else:
            out.append("")
        i += 1

    # 后处理：分两步
    # 第1步：修复 LaTeX 残留 + Markdown 标题
    # Markdown 标题判定：^#{1,6} 空格，且第一个词不是 Typst 指令（白名单）。
    # 白名单覆盖全部 Typst 内置函数/关键字，防止 #align/#counter/#grid 等被误转标题。
    _TYPST_FUNC_RE = re.compile(r"^#([a-zA-Z_][a-zA-Z0-9_]*)")
    _TYPST_WHITELIST = {
        # 布局
        "align", "figure", "v", "page", "box", "grid", "stack", "place",
        "pad", "h", "block", "columns", "row", "table", "caption",
        # 样式
        "show", "set", "text", "image", "heading", "strong", "emph",
        "link", "super", "sub", "underline", "highlight", "linebreak",
        "parbreak", "pagebreak", "footnote", "quote", "list", "enum",
        # 数学
        "math", "equation", "attach", "upright", "cal", "bb", "frak",
        "op", "lr", "abs", "norm", "floor", "ceil", "limits",
        # 编程/上下文
        "let", "import", "include", "if", "else", "for", "while",
        "return", "context", "counter", "state", "query", "here",
        "none", "auto", "true", "false",
        # 内置函数
        "calc", "str", "int", "float", "num", "bool", "type", "repr",
        "eval", "read", "write", "sys", "env", "assert", "panic",
        "length", "range", "enumerate", "zip", "map", "filter", "fold",
        "find", "min", "max", "sum", "product", "round", "floor",
        "array", "dictionary", "label", "reference", "bibliography",
    }

    result_lines = []
    for line in out:
        stripped = line.strip()
        # 修复 Markdown 标题：^# 开头且后续是标题语法（# 后跟空格）
        if re.match(r"^#{1,6}\s", stripped):
            m_fn = _TYPST_FUNC_RE.match(stripped)
            if not (m_fn and m_fn.group(1) in _TYPST_WHITELIST):
                hashes = len(stripped.split()[0])
                title = stripped[hashes:].strip()
                line = '=' * hashes + ' ' + title
        # 检测行内残留的 LaTeX 命令
        if '\\' in stripped and not stripped.startswith('//') and not stripped.startswith('#'):
            line = _math_convert(line)
        result_lines.append(line)
    # 第2步：修复 $ <eqN> 模式（收集下一行公式内容合并为单行）
    final_lines = []
    i = 0
    while i < len(result_lines):
        line = result_lines[i]
        stripped = line.strip()
        eq_match = re.search(r'\$ <(eq\d+)>', stripped)
        if eq_match:
            label = f'$ <{eq_match.group(1)}>'
            prefix = stripped[:eq_match.start()]
            if i + 1 < len(result_lines):
                formula = result_lines[i + 1].strip()
                if i + 2 < len(result_lines) and result_lines[i + 2].strip().isdigit():
                    i += 3
                else:
                    i += 2
                final_lines.append(f'{prefix} $ {formula} $ {label}')
                continue
        final_lines.append(line)
        i += 1

    # 最终清理：强制转换所有残留的 Markdown 标题
    # 与第1步同规则：正则白名单，避免 Typst 指令（#align/#counter/#grid 等）被误转标题
    for idx in range(len(final_lines)):
        stripped = final_lines[idx].strip()
        if re.match(r"^#{1,6}\s", stripped):
            m_fn = _TYPST_FUNC_RE.match(stripped)
            if not (m_fn and m_fn.group(1) in _TYPST_WHITELIST):
                hashes = len(stripped.split()[0])
                title = stripped[hashes:].strip()
                final_lines[idx] = '=' * hashes + ' ' + title

    return "\n".join(final_lines).strip() + "\n"
