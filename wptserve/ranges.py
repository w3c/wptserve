from utils import HTTPException

class RangeParser(object):
    def __call__(self, header, file_size):
        prefix = "bytes="
        if not header.startswith(prefix):
            raise HTTPException(400, message="Unrecognised range type %s" % (header,))

        parts = header[len(prefix):].split(",")
        ranges = []
        for item in parts:
            components = item.split("-")
            if len(components) != 2:
                raise HTTPException(400, "Bad range specifier %s" % (item))
            data = []
            for component in components:
                if component == "":
                    data.append(None)
                else:
                    try:
                        data.append(int(component))
                    except ValueError:
                        raise HTTPException(400, "Bad range specifier %s" % (item))
            ranges.append(Range(data[0], data[1], file_size))

        return self.coalesce_ranges(ranges, file_size)

    def coalesce_ranges(self, ranges, file_size):
        rv = []
        target = None
        for current in reversed(sorted(ranges)):
            if target is None:
                target = current
            else:
                new = target.coalesce(current)
                target = new[0]
                if len(new) > 1:
                    rv.append(new[1])
        rv.append(target)

        return rv[::-1]

class Range(object):
    def __init__(self, lower, upper, file_size):
        self.lower = lower
        self.upper = upper
        self.file_size = file_size


    def __repr__(self):
        return "<Range %s-%s>" % (self.lower, self.upper)

    def __lt__(self, other):
        return self.abs()[0] < other.abs()[0]

    def __gt__(self, other):
        return self.abs()[0] > other.abs()[0]

    def __eq__(self, other):
        self_lower, self_upper = self.abs()
        other_lower, other_upper = other.abs()

        return self_lower == other_lower and self_upper == other_upper

    def abs(self):
        if self.lower is None and self.upper is None:
            lower, upper = 0, self.file_size - 1
        elif self.lower is None:
            lower, upper = max(0, self.file_size - self.upper), self.file_size - 1
        elif self.upper is None:
            lower, upper = self.lower, self.file_size - 1
        else:
            lower, upper = self.lower, min(self.file_size - 1, self.upper)

        return lower, upper

    def coalesce(self, other):
        assert self.file_size == other.file_size
        self_lower, self_upper = self.abs()
        other_lower, other_upper = other.abs()

        if (self_upper < other_lower - 1 or self_lower - 1 > other_upper):
            return sorted([self, other])
        else:
            return [Range(min(self_lower, other_lower), max(self_upper, other_upper), self.file_size)]

    def header_value(self):
        lower, upper = self.abs()
        return "bytes %i-%i/%i" % (lower, upper, self.file_size)
