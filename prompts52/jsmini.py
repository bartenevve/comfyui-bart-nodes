"""A deliberately tiny JavaScript interpreter.

52prompts.com ships every generator as a standalone .js file: one
`generateThings()` function holding the word lists *and* the string templating
that turns them into a finished prompt. Scraping the arrays alone would only
get half the data - the sentence shapes live in the code - so producing the
same output the site produces means running the file, and Python has no
dependency-free JS engine to hand it to.

The subset implemented here is exactly what those 20 files use: var/if/for,
string concatenation, array literals, a handful of String/Array/Math methods
and a `document` shim. Anything outside it raises JSError rather than quietly
evaluating to nonsense, so a rewrite on the site's side surfaces as an error
message instead of a garbled prompt.
"""

import math
import re

MAX_LOOP_ITERATIONS = 1_000_000


class JSError(RuntimeError):
    pass


class _Undefined:
    """JS `undefined`, distinct from both None (`null`) and "" ."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "undefined"

    def __bool__(self):
        return False


UNDEFINED = _Undefined()


# ----------------------------------------------------------------- tokenizer

# longest first, so "===" is never read as "==" + "="
_PUNCTUATION = (
    "===",
    "!==",
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||",
    "++",
    "--",
    "=",
    "<",
    ">",
    "+",
    "-",
    "*",
    "/",
    "%",
    "!",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    ",",
    ";",
    ".",
    ":",
    "?",
)

_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_NUMBER = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")

_STRING_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
}


def _read_string(source, start):
    quote = source[start]
    out = []
    i = start + 1
    while i < len(source):
        ch = source[i]
        if ch == quote:
            return "".join(out), i + 1
        if ch == "\\":
            i += 1
            if i >= len(source):
                break
            escape = source[i]
            if escape == "u":
                out.append(chr(int(source[i + 1 : i + 5], 16)))
                i += 5
                continue
            if escape == "x":
                out.append(chr(int(source[i + 1 : i + 3], 16)))
                i += 3
                continue
            if escape == "\n":  # line continuation
                i += 1
                continue
            out.append(_STRING_ESCAPES.get(escape, escape))
            i += 1
            continue
        out.append(ch)
        i += 1
    raise JSError(f"unterminated string literal at offset {start}")


class Token:
    __slots__ = ("kind", "value", "newline_before", "offset")

    def __init__(self, kind, value, newline_before, offset):
        self.kind = kind  # "num" | "str" | "name" | "punc" | "eof"
        self.value = value
        self.newline_before = newline_before
        self.offset = offset

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r})"


def tokenize(source):
    tokens = []
    newline = True  # the first token counts as starting a line
    i = 0
    length = len(source)
    while i < length:
        ch = source[i]
        if ch == "\n":
            newline = True
            i += 1
            continue
        if ch in " \t\r\v\f ﻿":
            i += 1
            continue
        # The generator files separate their sections with HTML-style comments
        # ("<!------ Prompts ------>") pasted straight into the script. Browsers
        # accept those as line comments (Annex B), so we have to as well.
        if source.startswith("//", i) or source.startswith("<!--", i) or source.startswith("-->", i):
            newline_at = source.find("\n", i)
            i = length if newline_at < 0 else newline_at
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise JSError("unterminated block comment")
            if "\n" in source[i:end]:
                newline = True
            i = end + 2
            continue
        if ch in "'\"":
            value, i = _read_string(source, i)
            tokens.append(Token("str", value, newline, i))
            newline = False
            continue
        if ch.isdigit() or (ch == "." and i + 1 < length and source[i + 1].isdigit()):
            match = _NUMBER.match(source, i)
            tokens.append(Token("num", float(match.group(0)), newline, i))
            i = match.end()
            newline = False
            continue
        match = _NAME.match(source, i)
        if match:
            tokens.append(Token("name", match.group(0), newline, i))
            i = match.end()
            newline = False
            continue
        for punctuation in _PUNCTUATION:
            if source.startswith(punctuation, i):
                tokens.append(Token("punc", punctuation, newline, i))
                i += len(punctuation)
                newline = False
                break
        else:
            raise JSError(f"unexpected character {ch!r} at offset {i}")
    tokens.append(Token("eof", None, True, length))
    return tokens


# -------------------------------------------------------------------- parser

_KEYWORDS = {"var", "let", "const", "if", "else", "for", "return", "function", "new"}

_ASSIGNABLE = {"name", "index", "member"}


class Parser:
    """Recursive-descent parser producing tuple nodes."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.position = 0

    # --- token helpers

    def peek(self, offset=0):
        index = min(self.position + offset, len(self.tokens) - 1)
        return self.tokens[index]

    def advance(self):
        token = self.tokens[self.position]
        if token.kind != "eof":
            self.position += 1
        return token

    def at(self, kind, value=None):
        token = self.peek()
        return token.kind == kind and (value is None or token.value == value)

    def eat(self, kind, value=None):
        if self.at(kind, value):
            self.advance()
            return True
        return False

    def expect(self, kind, value=None):
        if not self.at(kind, value):
            token = self.peek()
            wanted = value if value is not None else kind
            raise JSError(
                f"expected {wanted!r} but found {token.value!r} at offset {token.offset}"
            )
        return self.advance()

    def end_statement(self):
        """Consume a statement terminator, applying newline-as-semicolon.

        The generator files leave semicolons off often enough (whole runs of
        `fun[71] = ...` with no terminator) that treating a line break as one
        is not optional.
        """
        if self.eat("punc", ";"):
            return
        token = self.peek()
        if token.kind == "eof" or token.newline_before or (token.kind == "punc" and token.value == "}"):
            return
        raise JSError(f"expected ';' before {token.value!r} at offset {token.offset}")

    # --- statements

    def parse_program(self):
        body = []
        while not self.at("eof"):
            body.append(self.parse_statement())
        return body

    def parse_statement(self):
        if self.at("punc", "{"):
            return self.parse_block()
        if self.at("punc", ";"):
            self.advance()
            return ("empty",)
        if self.at("name", "function"):
            return self.parse_function()
        if self.at("name", "var") or self.at("name", "let") or self.at("name", "const"):
            self.advance()
            declarations = self.parse_declarations()
            self.end_statement()
            return ("var", declarations)
        if self.at("name", "if"):
            return self.parse_if()
        if self.at("name", "for"):
            return self.parse_for()
        if self.at("name", "return"):
            self.advance()
            token = self.peek()
            if token.newline_before or self.at("punc", ";") or self.at("punc", "}") or self.at("eof"):
                self.end_statement()
                return ("return", None)
            value = self.parse_expression()
            self.end_statement()
            return ("return", value)
        expression = self.parse_expression()
        self.end_statement()
        return ("expr", expression)

    def parse_block(self):
        self.expect("punc", "{")
        body = []
        while not self.at("punc", "}"):
            if self.at("eof"):
                raise JSError("unterminated block")
            body.append(self.parse_statement())
        self.advance()
        return ("block", body)

    def parse_function(self):
        self.expect("name", "function")
        name = self.expect("name").value
        self.expect("punc", "(")
        parameters = []
        while not self.at("punc", ")"):
            parameters.append(self.expect("name").value)
            if not self.eat("punc", ","):
                break
        self.expect("punc", ")")
        body = self.parse_block()
        return ("function", name, parameters, body)

    def parse_declarations(self):
        declarations = []
        while True:
            name = self.expect("name").value
            initializer = self.parse_assignment() if self.eat("punc", "=") else None
            declarations.append((name, initializer))
            if not self.eat("punc", ","):
                return declarations

    def parse_if(self):
        self.expect("name", "if")
        self.expect("punc", "(")
        test = self.parse_expression()
        self.expect("punc", ")")
        consequent = self.parse_statement()
        alternate = None
        if self.at("name", "else"):
            self.advance()
            alternate = self.parse_statement()
        return ("if", test, consequent, alternate)

    def parse_for(self):
        self.expect("name", "for")
        self.expect("punc", "(")
        if self.at("punc", ";"):
            initializer = None
        elif self.at("name", "var") or self.at("name", "let") or self.at("name", "const"):
            self.advance()
            initializer = ("var", self.parse_declarations())
        else:
            initializer = ("expr", self.parse_expression())
        self.expect("punc", ";")
        test = None if self.at("punc", ";") else self.parse_expression()
        self.expect("punc", ";")
        update = None if self.at("punc", ")") else self.parse_expression()
        self.expect("punc", ")")
        body = self.parse_statement()
        return ("for", initializer, test, update, body)

    # --- expressions

    def parse_expression(self):
        expression = self.parse_assignment()
        while self.eat("punc", ","):
            expression = ("sequence", expression, self.parse_assignment())
        return expression

    def parse_assignment(self):
        left = self.parse_logical_or()
        if self.at("punc", "="):
            token = self.advance()
            if left[0] not in _ASSIGNABLE:
                raise JSError(f"cannot assign to {left[0]} at offset {token.offset}")
            return ("assign", left, self.parse_assignment())
        return left

    def _parse_binary(self, operators, sub_parser, node="binary"):
        left = sub_parser()
        while self.peek().kind == "punc" and self.peek().value in operators:
            operator = self.advance().value
            left = (node, operator, left, sub_parser())
        return left

    def parse_logical_or(self):
        return self._parse_binary(("||",), self.parse_logical_and, node="logical")

    def parse_logical_and(self):
        return self._parse_binary(("&&",), self.parse_equality, node="logical")

    def parse_equality(self):
        return self._parse_binary(("==", "!=", "===", "!=="), self.parse_relational)

    def parse_relational(self):
        return self._parse_binary(("<", ">", "<=", ">="), self.parse_additive)

    def parse_additive(self):
        return self._parse_binary(("+", "-"), self.parse_multiplicative)

    def parse_multiplicative(self):
        return self._parse_binary(("*", "/", "%"), self.parse_unary)

    def parse_unary(self):
        token = self.peek()
        if token.kind == "punc" and token.value in ("!", "-", "+"):
            self.advance()
            return ("unary", token.value, self.parse_unary())
        if token.kind == "punc" and token.value in ("++", "--"):
            self.advance()
            return ("prefix", token.value, self.parse_unary())
        return self.parse_postfix()

    def parse_postfix(self):
        expression = self.parse_call_member()
        token = self.peek()
        if token.kind == "punc" and token.value in ("++", "--") and not token.newline_before:
            self.advance()
            if expression[0] not in _ASSIGNABLE:
                raise JSError(f"cannot apply {token.value} at offset {token.offset}")
            return ("postfix", token.value, expression)
        return expression

    def parse_call_member(self):
        expression = self.parse_primary()
        while True:
            if self.eat("punc", "."):
                expression = ("member", expression, self.expect("name").value)
            elif self.eat("punc", "["):
                index = self.parse_expression()
                self.expect("punc", "]")
                expression = ("index", expression, index)
            elif self.at("punc", "("):
                expression = ("call", expression, self.parse_arguments())
            else:
                return expression

    def parse_arguments(self):
        self.expect("punc", "(")
        arguments = []
        while not self.at("punc", ")"):
            arguments.append(self.parse_assignment())
            if not self.eat("punc", ","):
                break
        self.expect("punc", ")")
        return arguments

    def parse_primary(self):
        token = self.peek()
        if token.kind == "num":
            self.advance()
            return ("number", token.value)
        if token.kind == "str":
            self.advance()
            return ("string", token.value)
        if token.kind == "punc" and token.value == "(":
            self.advance()
            expression = self.parse_expression()
            self.expect("punc", ")")
            return expression
        if token.kind == "punc" and token.value == "[":
            self.advance()
            elements = []
            while not self.at("punc", "]"):
                if self.eat("punc", ","):  # elision / trailing comma
                    continue
                elements.append(self.parse_assignment())
                if not self.eat("punc", ","):
                    break
            self.expect("punc", "]")
            return ("array", elements)
        if token.kind == "name":
            if token.value == "new":
                self.advance()
                callee = self.parse_primary()
                arguments = self.parse_arguments() if self.at("punc", "(") else []
                return ("new", callee, arguments)
            if token.value in _KEYWORDS:
                raise JSError(f"unsupported keyword {token.value!r} at offset {token.offset}")
            self.advance()
            return ("name", token.value)
        raise JSError(f"unexpected token {token.value!r} at offset {token.offset}")


def parse(source):
    return Parser(tokenize(source)).parse_program()


# ---------------------------------------------------------------- coercions


def js_string(value):
    if isinstance(value, str):
        return value
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is UNDEFINED:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number):
            return "NaN"
        if math.isinf(number):
            return "Infinity" if number > 0 else "-Infinity"
        if number == int(number) and abs(number) < 1e21:
            return str(int(number))
        return repr(number)
    if isinstance(value, list):
        # Array.prototype.toString: commas, with holes and undefined as ""
        return ",".join("" if item is UNDEFINED or item is None else js_string(item) for item in value)
    raise JSError(f"cannot convert {type(value).__name__} to string")


def js_number(value):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return 0.0
    if value is UNDEFINED:
        return float("nan")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return float("nan")
    if isinstance(value, list):
        return js_number(js_string(value))
    raise JSError(f"cannot convert {type(value).__name__} to number")


def js_truthy(value):
    if isinstance(value, bool):
        return value
    if value is None or value is UNDEFINED:
        return False
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (int, float)):
        number = float(value)
        return number != 0 and not math.isnan(number)
    return True


def js_add(left, right):
    # arrays (and our objects) go through ToPrimitive first
    if isinstance(left, list):
        left = js_string(left)
    if isinstance(right, list):
        right = js_string(right)
    if isinstance(left, str) or isinstance(right, str):
        return js_string(left) + js_string(right)
    return js_number(left) + js_number(right)


def js_loose_equals(left, right):
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    if (left is None or left is UNDEFINED) or (right is None or right is UNDEFINED):
        return (left is None or left is UNDEFINED) and (right is None or right is UNDEFINED)
    return js_number(left) == js_number(right)


def js_strict_equals(left, right):
    if isinstance(left, str) != isinstance(right, str):
        return False
    if isinstance(left, str):
        return left == right
    if left is UNDEFINED or right is UNDEFINED:
        return left is right
    if left is None or right is None:
        return left is right
    return js_number(left) == js_number(right)


def _to_integer(value):
    """ToInteger: truncate toward zero, NaN becomes 0."""
    number = js_number(value)
    if math.isnan(number):
        return 0
    if math.isinf(number):
        return int(math.copysign(2**53, number))
    return int(number)


def _array_index(key):
    """The integer a property key addresses, or None if it addresses no slot."""
    if isinstance(key, bool):
        return None
    if isinstance(key, (int, float)):
        number = float(key)
        if math.isnan(number) or number != int(number):
            return None  # arr[1.7] is a plain property in JS, not element 1
        return int(number)
    if isinstance(key, str):
        try:
            number = float(key.strip())
        except ValueError:
            return None
        return int(number) if number == int(number) else None
    return None


# ------------------------------------------------------------------ runtime


class Element:
    """The bits of a DOM element the generators touch."""

    def __init__(self, element_id, value="", selected=False):
        self.element_id = element_id
        self.value = value
        self.selected = selected
        self.inner_html = ""

    def get(self, name):
        if name == "value":
            return self.value
        if name == "selected":
            return self.selected
        if name in ("innerHTML", "textContent", "innerText"):
            return self.inner_html
        if name == "checked":
            return self.selected
        if name == "id":
            return self.element_id
        raise JSError(f"unsupported element property: {name}")

    def set(self, name, value):
        if name in ("innerHTML", "textContent", "innerText"):
            self.inner_html = js_string(value)
            return
        if name == "value":
            self.value = js_string(value)
            return
        raise JSError(f"unsupported element property assignment: {name}")


class Document:
    """A `document` stand-in backed by caller-supplied field values.

    Every id the script asks for resolves to an element, whether the caller
    named it or not - a generator reaching for an input we did not anticipate
    should read as an empty field, not crash the run.
    """

    def __init__(self, values=None, selected=()):
        self.values = dict(values or {})
        self.selected_ids = set(selected)
        self.elements = {}

    def get_element(self, element_id):
        element = self.elements.get(element_id)
        if element is None:
            element = Element(
                element_id,
                value=self.values.get(element_id, ""),
                selected=element_id in self.selected_ids,
            )
            self.elements[element_id] = element
        return element

    def written(self, element_id):
        element = self.elements.get(element_id)
        return element.inner_html if element else ""


class _MathObject:
    pass


class _DocumentReference:
    pass


MATH = _MathObject()


class _Return(Exception):
    def __init__(self, value):
        self.value = value


class Interpreter:
    """Executes a parsed generator script against one `document` and one RNG.

    `var` is function-scoped and every generator is a single function, so one
    flat scope is not a shortcut here - it is what the language does.
    """

    def __init__(self, document, rng):
        self.document = document
        self.rng = rng
        self.scope = {}
        self.functions = {}

    # --- entry points

    def run(self, program, entry="generateThings"):
        for statement in program:
            if statement[0] == "function":
                self.functions[statement[1]] = statement
        try:
            for statement in program:
                if statement[0] != "function":
                    self.execute(statement)
        except _Return:
            pass

        function = self.functions.get(entry)
        if function is None:
            if not self.functions:
                return
            if len(self.functions) > 1:
                raise JSError(f"script has no {entry}() to call")
            function = next(iter(self.functions.values()))
        self.call_function(function, [])

    def call_function(self, function, arguments):
        _, _, parameters, body = function
        for index, parameter in enumerate(parameters):
            self.scope[parameter] = arguments[index] if index < len(arguments) else UNDEFINED
        try:
            self.execute(body)
        except _Return as returned:
            return returned.value
        return UNDEFINED

    # --- statements

    def execute(self, statement):
        kind = statement[0]
        if kind == "expr":
            self.evaluate(statement[1])
        elif kind == "var":
            for name, initializer in statement[1]:
                value = self.evaluate(initializer) if initializer is not None else UNDEFINED
                if initializer is not None or name not in self.scope:
                    self.scope[name] = value
        elif kind == "block":
            for inner in statement[1]:
                self.execute(inner)
        elif kind == "if":
            if js_truthy(self.evaluate(statement[1])):
                self.execute(statement[2])
            elif statement[3] is not None:
                self.execute(statement[3])
        elif kind == "for":
            self.execute_for(statement)
        elif kind == "return":
            raise _Return(self.evaluate(statement[1]) if statement[1] is not None else UNDEFINED)
        elif kind == "function":
            self.functions[statement[1]] = statement
        elif kind == "empty":
            pass
        else:
            raise JSError(f"unsupported statement: {kind}")

    def execute_for(self, statement):
        _, initializer, test, update, body = statement
        if initializer is not None:
            self.execute(initializer)
        iterations = 0
        while test is None or js_truthy(self.evaluate(test)):
            iterations += 1
            if iterations > MAX_LOOP_ITERATIONS:
                raise JSError("loop exceeded the iteration limit")
            self.execute(body)
            if update is not None:
                self.evaluate(update)

    # --- expressions

    def evaluate(self, node):
        kind = node[0]
        if kind == "number" or kind == "string":
            return node[1]
        if kind == "name":
            return self.lookup(node[1])
        if kind == "array":
            return [self.evaluate(element) for element in node[1]]
        if kind == "binary":
            return self.evaluate_binary(node[1], node[2], node[3])
        if kind == "logical":
            left = self.evaluate(node[2])
            if node[1] == "&&":
                return self.evaluate(node[3]) if js_truthy(left) else left
            return left if js_truthy(left) else self.evaluate(node[3])
        if kind == "unary":
            return self.evaluate_unary(node[1], node[2])
        if kind == "assign":
            value = self.evaluate(node[2])
            self.assign(node[1], value)
            return value
        if kind == "postfix" or kind == "prefix":
            old = js_number(self.evaluate(node[2]))
            new = old + (1 if node[1] == "++" else -1)
            self.assign(node[2], new)
            return old if kind == "postfix" else new
        if kind == "member":
            return self.get_member(self.evaluate(node[1]), node[2])
        if kind == "index":
            return self.get_index(self.evaluate(node[1]), self.evaluate(node[2]))
        if kind == "call":
            return self.evaluate_call(node[1], node[2])
        if kind == "new":
            return self.evaluate_new(node[1], node[2])
        if kind == "sequence":
            self.evaluate(node[1])
            return self.evaluate(node[2])
        raise JSError(f"unsupported expression: {kind}")

    def evaluate_binary(self, operator, left_node, right_node):
        left = self.evaluate(left_node)
        right = self.evaluate(right_node)
        if operator == "+":
            return js_add(left, right)
        if operator == "-":
            return js_number(left) - js_number(right)
        if operator == "*":
            return js_number(left) * js_number(right)
        if operator == "/":
            divisor = js_number(right)
            if divisor == 0:
                return float("nan") if js_number(left) == 0 else math.copysign(float("inf"), divisor)
            return js_number(left) / divisor
        if operator == "%":
            divisor = js_number(right)
            if divisor == 0:
                return float("nan")
            return math.fmod(js_number(left), divisor)
        if operator == "==":
            return js_loose_equals(left, right)
        if operator == "!=":
            return not js_loose_equals(left, right)
        if operator == "===":
            return js_strict_equals(left, right)
        if operator == "!==":
            return not js_strict_equals(left, right)
        if operator in ("<", ">", "<=", ">="):
            if isinstance(left, str) and isinstance(right, str):
                pair = (left, right)
            else:
                pair = (js_number(left), js_number(right))
                if math.isnan(pair[0]) or math.isnan(pair[1]):
                    return False
            if operator == "<":
                return pair[0] < pair[1]
            if operator == ">":
                return pair[0] > pair[1]
            if operator == "<=":
                return pair[0] <= pair[1]
            return pair[0] >= pair[1]
        raise JSError(f"unsupported operator: {operator}")

    def evaluate_unary(self, operator, operand_node):
        value = self.evaluate(operand_node)
        if operator == "!":
            return not js_truthy(value)
        if operator == "-":
            return -js_number(value)
        return js_number(value)

    # --- names, members, indexes

    def lookup(self, name):
        if name in self.scope:
            return self.scope[name]
        if name == "Math":
            return MATH
        if name == "document":
            return self.document
        if name == "undefined":
            return UNDEFINED
        if name == "null":
            return None
        if name == "NaN":
            return float("nan")
        if name == "true":
            return True
        if name == "false":
            return False
        if name in ("parseInt", "parseFloat", "String", "Number", "Boolean", "Array", "isNaN"):
            return ("builtin", name)
        if name in self.functions:
            return ("function", name)
        raise JSError(f"reference to undefined variable: {name}")

    def assign(self, target, value):
        kind = target[0]
        if kind == "name":
            self.scope[target[1]] = value
            return
        if kind == "index":
            container = self.evaluate(target[1])
            key = self.evaluate(target[2])
            if isinstance(container, list):
                index = _array_index(key)
                if index is None or index < 0:
                    raise JSError(f"unsupported array key: {key!r}")
                while len(container) <= index:
                    container.append(UNDEFINED)
                container[index] = value
                return
            raise JSError(f"cannot index-assign on {type(container).__name__}")
        if kind == "member":
            container = self.evaluate(target[1])
            if isinstance(container, Element):
                container.set(target[2], value)
                return
            raise JSError(f"cannot set .{target[2]} on {type(container).__name__}")
        raise JSError(f"cannot assign to {kind}")

    def get_member(self, container, name):
        if isinstance(container, Element):
            return container.get(name)
        if isinstance(container, (str, list)) and name == "length":
            return float(len(container))
        if isinstance(container, (str, list, Document, _MathObject)):
            # a method reference; only ever used as the callee of a call
            return ("method", container, name)
        raise JSError(f"unsupported property access: .{name}")

    def get_index(self, container, key):
        if isinstance(container, list):
            index = _array_index(key)
            if index is None or index < 0 or index >= len(container):
                return UNDEFINED
            return container[index]
        if isinstance(container, str):
            index = _array_index(key)
            if index is None or index < 0 or index >= len(container):
                return UNDEFINED
            return container[index]
        raise JSError(f"cannot index {type(container).__name__}")

    # --- calls

    def evaluate_call(self, callee_node, argument_nodes):
        arguments = [self.evaluate(argument) for argument in argument_nodes]

        if callee_node[0] == "member":
            container = self.evaluate(callee_node[1])
            return self.call_method(container, callee_node[2], arguments)

        callee = self.evaluate(callee_node)
        if isinstance(callee, tuple):
            if callee[0] == "builtin":
                return self.call_builtin(callee[1], arguments)
            if callee[0] == "method":
                return self.call_method(callee[1], callee[2], arguments)
            if callee[0] == "function":
                return self.call_function(self.functions[callee[1]], arguments)
        raise JSError("attempted to call a non-function value")

    def evaluate_new(self, callee_node, argument_nodes):
        if callee_node[0] != "name":
            raise JSError("unsupported constructor expression")
        name = callee_node[1]
        arguments = [self.evaluate(argument) for argument in argument_nodes]
        if name == "Array":
            return self.call_builtin("Array", arguments)
        raise JSError(f"unsupported constructor: new {name}")

    def call_builtin(self, name, arguments):
        first = arguments[0] if arguments else UNDEFINED
        if name == "Array":
            if len(arguments) == 1 and isinstance(first, (int, float)) and not isinstance(first, bool):
                return [UNDEFINED] * _to_integer(first)
            return list(arguments)
        if name == "String":
            return js_string(first) if arguments else ""
        if name == "Number":
            return js_number(first) if arguments else 0.0
        if name == "Boolean":
            return js_truthy(first)
        if name == "isNaN":
            return math.isnan(js_number(first))
        if name in ("parseInt", "parseFloat"):
            text = js_string(first).strip()
            pattern = r"[+-]?\d+" if name == "parseInt" else r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
            match = re.match(pattern, text)
            if not match:
                return float("nan")
            return float(int(match.group(0))) if name == "parseInt" else float(match.group(0))
        raise JSError(f"unsupported builtin: {name}")

    def call_method(self, container, name, arguments):
        if isinstance(container, _MathObject):
            return self.call_math(name, arguments)
        if isinstance(container, Document):
            if name == "getElementById":
                return container.get_element(js_string(arguments[0] if arguments else ""))
            raise JSError(f"unsupported document method: {name}")
        if isinstance(container, str):
            return _string_method(container, name, arguments)
        if isinstance(container, list):
            return _array_method(container, name, arguments)
        raise JSError(f"unsupported method call: .{name}() on {type(container).__name__}")

    def call_math(self, name, arguments):
        if name == "random":
            return self.rng.random()
        values = [js_number(argument) for argument in arguments]
        first = values[0] if values else float("nan")
        if name == "floor":
            return float(math.floor(first)) if not math.isnan(first) else first
        if name == "ceil":
            return float(math.ceil(first)) if not math.isnan(first) else first
        if name == "round":
            return float(math.floor(first + 0.5)) if not math.isnan(first) else first
        if name == "abs":
            return abs(first)
        if name == "trunc":
            return float(_to_integer(first))
        if name == "sqrt":
            return math.sqrt(first) if first >= 0 else float("nan")
        if name == "pow":
            return float(first ** values[1])
        if name == "min":
            return min(values) if values else float("inf")
        if name == "max":
            return max(values) if values else float("-inf")
        raise JSError(f"unsupported Math method: {name}")


def _string_method(text, name, arguments):
    first = arguments[0] if arguments else UNDEFINED
    if name == "charAt":
        index = _to_integer(first) if arguments else 0
        return text[index] if 0 <= index < len(text) else ""
    if name == "toUpperCase":
        return text.upper()
    if name == "toLowerCase":
        return text.lower()
    if name == "trim":
        return text.strip()
    if name == "substr":
        start = _to_integer(first) if arguments else 0
        if start < 0:
            start = max(len(text) + start, 0)
        if len(arguments) < 2 or arguments[1] is UNDEFINED:
            return text[start:]
        count = _to_integer(arguments[1])
        return text[start : start + count] if count > 0 else ""
    if name in ("substring", "slice"):
        start = _to_integer(first) if arguments else 0
        end = _to_integer(arguments[1]) if len(arguments) > 1 and arguments[1] is not UNDEFINED else len(text)
        if name == "slice":
            if start < 0:
                start = max(len(text) + start, 0)
            if end < 0:
                end = max(len(text) + end, 0)
        else:
            start = min(max(start, 0), len(text))
            end = min(max(end, 0), len(text))
            if start > end:
                start, end = end, start
        return text[start:end] if start < end else ""
    if name == "indexOf":
        return float(text.find(js_string(first)))
    if name == "lastIndexOf":
        return float(text.rfind(js_string(first)))
    if name == "split":
        if not arguments or first is UNDEFINED:
            return [text]
        separator = js_string(first)
        return list(text) if separator == "" else text.split(separator)
    if name == "replace":
        return text.replace(js_string(first), js_string(arguments[1]), 1)
    if name == "concat":
        return text + "".join(js_string(argument) for argument in arguments)
    if name == "includes":
        return js_string(first) in text
    if name == "toString":
        return text
    raise JSError(f"unsupported String method: {name}")


def _array_method(items, name, arguments):
    first = arguments[0] if arguments else UNDEFINED
    if name == "push":
        items.extend(arguments)
        return float(len(items))
    if name == "pop":
        return items.pop() if items else UNDEFINED
    if name == "shift":
        return items.pop(0) if items else UNDEFINED
    if name == "unshift":
        items[:0] = arguments
        return float(len(items))
    if name == "splice":
        start = _to_integer(first) if arguments else 0
        if start < 0:
            start = max(len(items) + start, 0)
        start = min(start, len(items))
        if len(arguments) < 2:
            count = len(items) - start
        else:
            count = max(_to_integer(arguments[1]), 0)
        removed = items[start : start + count]
        items[start : start + count] = list(arguments[2:])
        return removed
    if name == "join":
        separator = "," if not arguments or first is UNDEFINED else js_string(first)
        return separator.join(
            "" if item is UNDEFINED or item is None else js_string(item) for item in items
        )
    if name == "indexOf":
        for index, item in enumerate(items):
            if js_strict_equals(item, first):
                return float(index)
        return -1.0
    if name == "slice":
        start = _to_integer(first) if arguments else 0
        if start < 0:
            start = max(len(items) + start, 0)
        end = _to_integer(arguments[1]) if len(arguments) > 1 and arguments[1] is not UNDEFINED else len(items)
        if end < 0:
            end = max(len(items) + end, 0)
        return items[start:end]
    if name == "concat":
        result = list(items)
        for argument in arguments:
            result.extend(argument) if isinstance(argument, list) else result.append(argument)
        return result
    if name == "reverse":
        items.reverse()
        return items
    if name == "toString":
        return js_string(items)
    raise JSError(f"unsupported Array method: {name}")


def run_script(source, values=None, selected=(), rng=None, output_id="promptDisplay"):
    """Run a generator script and return what it wrote into `output_id`.

    `values` maps DOM ids to the text of that field; `selected` is the set of
    ids whose `.selected` should read true.
    """
    import random as random_module

    document = Document(values=values, selected=selected)
    interpreter = Interpreter(document, rng if rng is not None else random_module.Random())
    interpreter.run(parse(source))
    return document.written(output_id)
