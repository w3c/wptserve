import types

def resolve_content(response):
    return "".join(item for item in response.iter_content())

class Pipeline(object):
    pipes = {}

    def __init__(self, pipe_string):
        self.pipe_functions = self.parse(pipe_string)

    def parse(self, pipe_string):
        functions = []
        for item in PipeTokenizer().tokenize(pipe_string):
            if not item:
                break
            if item[0] == "function":
                functions.append((self.pipes[item[1]], []))
            elif item[0] == "argument":
                functions[-1][1].append(item[1])
        return functions

    def __call__(self, response):
        for func, args in self.pipe_functions:
            response = func(response, *args)
        return response

class PipeTokenizer(object):
    def __init__(self):
        #This whole class can likely be replaced by some regexps
        self.state = None
   
    def tokenize(self, string):
        self.string = string
        self.state = self.func_name_state
        self._index = 0
        while self.state:
            yield self.state()
        yield None

    def get_char(self):
        if self._index >= len(self.string):
            return None
        rv = self.string[self._index]
        self._index += 1
        return rv

    def func_name_state(self):
        rv = ""
        while True:
            char = self.get_char()
            if char is None:
                self.state = None
                if rv:
                    return ("function", rv)
                else:
                    return None
            elif char == "(":
                self.state = self.argument_state
                return ("function", rv)
            elif char == "|":
                if rv:
                    return ("function", rv)
            else:
                rv += char

    def argument_state(self):
        rv = ""
        while True:
            char = self.get_char()
            if char is None:
                self.state = None
                return ("argument", rv)
            elif char == "\\":
                rv += self.get_escape()
                if rv is None:
                    #This should perhaps be an error instead
                    return ("argument", rv)
            elif char == ",":
                return ("argument", rv)
            elif char == ")":
                self.state = self.func_name_state
                return ("argument", rv)
            else:
                rv += char

    def get_escape(self):
        char = self.get_char()
        escapes = {"n": "\n",
                   "r": "\r",
                   "t": "\t"}
        return escapes.get(char, char)

class pipe(object):
    def __init__(self, *arg_converters):
        self.arg_converters = arg_converters
        self.max_args = len(self.arg_converters)
        self.min_args = 0
        opt_seen = False
        for item in self.arg_converters:
            if not opt_seen:
                if isinstance(item, opt):
                    opt_seen = True
                else:
                    self.min_args += 1
            else:
                if not isinstance(item, opt):
                    raise ValueError("Non-optional argument cannot follow optional argument")

    def __call__(self, f):
        def inner(response, *args):
            if not (self.min_args <= len(args) <= self.max_args):
                raise ValueError
            arg_values = tuple(f(x) for f,x in zip(self.arg_converters, args))
            return f(response, *arg_values)
        Pipeline.pipes[f.__name__] = inner
        #We actually want the undecorated function in the main namespace
        return f

class opt(object):
    def __init__(self, f):
        self.f = f

    def __call__(self, arg):
        return self.f(arg)
    
def nullable(func):
    def inner(arg):
        if arg.lower() == "null":
            return None
        else:
            return func(arg)
    return inner

@pipe(int)
def status(response, code):
    response.status = code
    return response

@pipe(str, str)
def header(response, name, value):
    name_lower = name.lower()
    headers = [item for item in response.headers if item[0].lower() != name_lower]
    headers.append((name, value))
    response.headers = headers
    return response

@pipe(str)
def trickle(response, delays):
    import time
    def parse_delays():
        parts = delays.split(":")
        rv = []
        for item in parts:
            if item.startswith("d"):
                item_type = "delay"
                item = item[1:]
                value=float(item)
            else:
                item_type = "bytes"
                value = int(item)
            if len(rv) and rv[-1][0] == item_type:
                rv[-1][1] += value
            else:
                rv.append((item_type, value))
        return rv
    delays = parse_delays()
    if not delays:
        return response
    content = resolve_content(response)
    modified_content = []
    offset = 0

    def sleep(seconds):
        def inner():
            time.sleep(seconds)
            return ""
        return inner

    for item_type, value in delays:
        if item_type == "bytes":
            modified_content.append(content[offset:offset + value])
            offset += value
        elif item_type == "delay":
            modified_content.append(sleep(value))

    if offset < len(content):
        modified_content.append(content[offset:])
    response.content = modified_content
    return response

@pipe(nullable(int), opt(nullable(int)))
def slice(response, start, end=None):
    content = resolve_content(response)
    response.content = content[start:end]
    return response
