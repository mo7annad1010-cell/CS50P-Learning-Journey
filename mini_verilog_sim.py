"""
mini_verilog_sim.py - مفسّر Verilog مصغّر
المراحل: نص -> Tokens -> AST (شجرة) -> محاكاة بقيم X وساعة
يدعم: input/output/wire/reg, assign, always @(posedge clk) مع <=
العمليات: ~ & | ^ + - == != ?: والأقواس
"""
import re

# ============ المرحلة 1: التقطيع (Lexer) ============
TOK = re.compile(
    r"\s*(?:(\d+'[bBdDhH][0-9a-fA-F_]+)|(\d+)|([A-Za-z_]\w*)"
    r"|(<=|==|!=|[-+&|^~?:()\[\];,=@]))"
)

def tokenize(src):
    src = re.sub(r"//.*", "", src).rstrip()
    out, i = [], 0
    while i < len(src):
        m = TOK.match(src, i)
        if not m:
            raise SyntaxError(f"حرف غير مفهوم عند: {src[i:i+10]!r}")
        out.append(m.group(m.lastindex))
        i = m.end()
    return out

def literal(t):
    """'4'b1010' -> (10, 4) ، '7' -> (7, None)"""
    if "'" in t:
        w, rest = t.split("'")
        base = {"b": 2, "d": 10, "h": 16}[rest[0].lower()]
        return int(rest[1:].replace("_", ""), base), int(w)
    return int(t), None

# ============ المرحلة 2: المحلل (Parser) ============
class Parser:
    PREC = {"|": 1, "^": 2, "&": 3, "==": 4, "!=": 4, "+": 5, "-": 5}

    def __init__(s, toks):
        s.t, s.i = toks, 0

    def peek(s):
        return s.t[s.i] if s.i < len(s.t) else None

    def next(s):
        tok = s.peek()
        s.i += 1
        return tok

    def expect(s, x):
        got = s.next()
        if got != x:
            raise SyntaxError(f"توقعت {x!r} لكن وجدت {got!r}")

    def module(s):
        m = dict(name=None, widths={}, inputs=[], outputs=[],
                 assigns=[], seqs=[])
        s.expect("module")
        m["name"] = s.next()
        s.expect("(")
        while s.next() != ")":
            pass
        s.expect(";")
        while s.peek() != "endmodule":
            k = s.next()
            if k in ("input", "output", "wire", "reg"):
                if s.peek() == "reg":
                    s.next()
                w = 1
                if s.peek() == "[":
                    s.next()
                    hi = int(s.next())
                    s.expect(":"); s.expect("0"); s.expect("]")
                    w = hi + 1
                while True:
                    n = s.next()
                    m["widths"][n] = w
                    if k == "input":
                        m["inputs"].append(n)
                    if k == "output":
                        m["outputs"].append(n)
                    if s.next() == ";":
                        break
            elif k == "assign":
                t = s.next(); s.expect("=")
                m["assigns"].append((t, s.expr()))
                s.expect(";")
            elif k == "always":
                for x in ("@", "(", "posedge"):
                    s.expect(x)
                clk = s.next()
                s.expect(")"); s.expect("begin")
                body = []
                while s.peek() != "end":
                    t = s.next(); s.expect("<=")
                    body.append((t, s.expr()))
                    s.expect(";")
                s.expect("end")
                m["seqs"].append((clk, body))
            else:
                raise SyntaxError(f"كلمة غير مدعومة: {k!r}")
        return m

    # تعبيرات: الأولوية عبر PREC (طريقة Precedence Climbing)
    def expr(s):
        c = s.binary(1)
        if s.peek() == "?":
            s.next()
            a = s.expr()
            s.expect(":")
            b = s.expr()
            return ("?", c, a, b)
        return c

    def binary(s, minp):
        left = s.unary()
        while s.peek() in s.PREC and s.PREC[s.peek()] >= minp:
            op = s.next()
            right = s.binary(s.PREC[op] + 1)
            left = ("bin", op, left, right)
        return left

    def unary(s):
        t = s.next()
        if t == "~":
            return ("not", s.unary())
        if t == "(":
            e = s.expr()
            s.expect(")")
            return e
        if t[0].isdigit():
            return ("num",) + literal(t)
        return ("id", t)

# ============ المرحلة 3: التقييم (4-state: 0 / 1 / X) ============
# القيمة None تعني X (مجهول)
OPS = {"&": lambda a, b: a & b, "|": lambda a, b: a | b,
       "^": lambda a, b: a ^ b, "+": lambda a, b: a + b,
       "-": lambda a, b: a - b,
       "==": lambda a, b: int(a == b), "!=": lambda a, b: int(a != b)}

def ev(n, vals, mask):
    k = n[0]
    if k == "num":
        return n[1] & mask
    if k == "id":
        return vals[n[1]]
    if k == "not":
        a = ev(n[1], vals, mask)
        return None if a is None else ~a & mask
    if k == "?":
        c = ev(n[1], vals, mask)
        a, b = ev(n[2], vals, mask), ev(n[3], vals, mask)
        if c is None:                     # الشرط مجهول
            return a if a == b else None  # لو الفرعان متساويان فالنتيجة معروفة
        return a if c else b
    op, l, r = n[1], ev(n[2], vals, mask), ev(n[3], vals, mask)
    if op == "&" and (l == 0 or r == 0):
        return 0                          # 0 AND أي شيء = 0 حتى لو X
    if op == "|" and (l == mask or r == mask):
        return mask
    if l is None or r is None:
        return None                       # X ينتشر
    return OPS[op](l, r) & mask

# ============ المرحلة 4: المحاكي ============
class Sim:
    def __init__(s, src):
        s.m = Parser(tokenize(src)).module()
        s.w = s.m["widths"]
        s.v = {n: None for n in s.w}      # كل شيء يبدأ X

    def mask(s, n):
        return (1 << s.w[n]) - 1

    def settle(s):
        """كرّر الحساب التوافقي حتى يستقر (Fixed Point)."""
        for _ in range(100):
            changed = False
            for t, e in s.m["assigns"]:
                x = ev(e, s.v, s.mask(t))
                if x is not None:
                    x &= s.mask(t)
                if x != s.v[t]:
                    s.v[t], changed = x, True
            if not changed:
                return
        raise RuntimeError("حلقة توافقية: الدائرة لا تستقر")

    def set(s, name, val):
        s.v[name] = val & s.mask(name)
        s.settle()

    def clock(s, clk="clk"):
        """نبضة ساعة: نحسب كل RHS أولاً ثم نثبّت معاً (معنى <=)."""
        s.v[clk] = 0
        s.settle()
        pending = []
        for c, body in s.m["seqs"]:
            if c == clk:
                for t, e in body:
                    x = ev(e, s.v, s.mask(t))
                    pending.append((t, None if x is None else x & s.mask(t)))
        s.v[clk] = 1
        for t, x in pending:
            s.v[t] = x
        s.settle()

    def show(s, *names):
        def f(n):
            x = s.v[n]
            return "x" * s.w[n] if x is None else format(x, f"0{s.w[n]}b")
        return "  ".join(f"{n}={f(n)}" for n in names)

# ============ تجربة: عدّاد 4 بت ============
COUNTER = """
module counter(clk, rst, en, count, odd);
    input clk; input rst; input en;
    output reg [3:0] count;
    output odd;
    wire [3:0] nxt;
    assign nxt = rst ? 4'd0 : (en ? count + 4'd1 : count);
    assign odd = count & 4'd1;
    always @(posedge clk) begin
        count <= nxt;
    end
endmodule
"""

if __name__ == "__main__":
    sim = Sim(COUNTER)
    sim.set("rst", 0)
    sim.set("en", 1)
    print("قبل reset:  ", sim.show("count", "odd"))
    sim.clock()
    print("نبضة بلا reset:", sim.show("count", "odd"), " <- X لا يزول وحده")
    sim.set("rst", 1)
    sim.clock()
    print("بعد reset:  ", sim.show("count", "odd"))
    sim.set("rst", 0)
    for i in range(20):
        sim.clock()
        print(f"نبضة {i+1}:     ", sim.show("count", "odd"))
