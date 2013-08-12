def invert_dict(dict):
    rv = {}
    for key, values in dict.iteritems():
        for value in values:
            if value in rv:
                raise ValueError
            rv[value] = key
    return rv
