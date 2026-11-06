import argparse
from ast import alias
from enum import Enum
import re
from typing import Counter, List
try:
    from devtools import debug
except ImportError:  # devtools is optional, only used with --verbose
    def debug(*args):
        print(*args)
from os.path import basename, abspath
from pathlib import Path


STR_SNIPPET = (
"""
{name} = custom_get(option="{option}", 
                    section= "Validation",
                    fallback= {fallback},
                    apply={apply}
         )
""")
REGEX_SNIPPET = STR_SNIPPET

INT_SNIPPET = (
"""
{name} = config.getint(option="{option}", 
                       section= "Validation",
                       fallback= {fallback})
""")
usage_string = """py add_setting.py \"setting1 = value1; setting2 = value2\" [--str|--regex|--float|--int] [--apply lambda x: x.split(';')] `
[--ini-file="/mnt/c/some/file/path/file.ini"](looks for validation.ini by default) [--py-file="/mnt/c/some/file/path/file.py"](looks for validation_config.py by default)
"""

def parse():
    parser = argparse.ArgumentParser(prog="py " + basename(__file__),
                                     description=("Add settings to the *.ini configuration"
                                                  " files and generate the code that"
                                                  " reads them in *.py."), usage=usage_string)

    parser.add_argument("setting",
                        nargs="*",
                        metavar="N",
                        help=("option up to the first \"=\" followed by the value. Multiple values are allowed."
                              " Line breaks (with \"`\" in PowerShell) and spaces are allowed"
                              " (spaces are removed from the final result)"))

    parser.add_argument("--ini-file", nargs="?",
                        default=next(Path().glob("**/validation.ini")),
                        help="\tpath to the *.ini file")
    parser.add_argument("--py-file",
                        nargs="?", default=next(Path().glob("**/validation_config.py")),
                        help="\tpath to the *.py file")

    parser.add_argument("--regex", action="store_true", help="The value being set is a regular expression.")
    parser.add_argument("--int", action="store_true", help="The value being set is an integer.")
    parser.add_argument("--str", action="store_true", help="The value being set is a string.")
    parser.add_argument("--float", action="store_true", help="The value being set is a floating point number.")

    parser.add_argument("--verbose", action="store_true", help="print every write operation")
    parser.add_argument("--apply", dest="apply", nargs="?", default="DO_NOTHING", help="Function whose only argument is the value string.")
    parser.add_argument("--split", default=";", metavar="C", help="Character used to split the provided string into substrings (; by default)")
    return parser.parse_args()
def arguments_valid(n: argparse.Namespace) -> bool:
    type_counter = Counter([n.regex, n.int, n.str, n.float])
    if type_counter[True] > 1:
        return False
    else: 
        return True

def write(n: argparse.Namespace):
    settings = dict()

    try:
        for s in re.finditer(r"(?P<key>.*?)\s*=\s*(?P<value>.*)", " ".join(n.setting)):
            split_value = s.group("value").split(n.split)
            if len(split_value) > 1:
                settings[s.group("key")] =  split_value
            else:
                settings[s.group("key")] =  split_value[0]

    except AttributeError:
        print("attr_ERROR")
    with open(abspath(n.ini_file), encoding="utf-8") as ini_file:
        for line in ini_file:
            for k in settings.copy().keys():
                if re.match(f"(?i)({k})", line):
                    print(k+" already exists in "+ basename(n.ini_file) + ". Setting addition aborted.")
                    del settings[k]
    with open(abspath(n.py_file), encoding="utf-8") as py_file:
        for line in py_file:
            for k in settings.copy().keys():
                if re.match("(?i)({k})", line):
                    print(k+" already exists in "+ basename(n.py_file)+ ". Setting addition aborted.")
                    del settings[k]
    with open(abspath(n.ini_file), encoding="utf-8", mode="at") as ini_file_at:
        for k, v in settings.items():
            if ini_file_at.writable():
                if isinstance(v, list):  
                    first_line = f"{k}: {v[0]}"
                else:
                    first_line = f"{k}: {v}"
                ini_file_at.write("\n"+first_line)
                if n.verbose:
                    print("FILE:\n\n")
                    debug(ini_file_at)
                    print("WROTE:\n\n")
                    print(first_line)
                first_line = first_line.find(":")
                if isinstance(v, list):
                    for element in v[1:]:
                        ini_file_at.write("\n"+(" " * (first_line+2))+element)
                        if n.verbose:
                            print((" " * (first_line+2))+element)
            else: 
                print("The file is not writable.")
            
    with open(abspath(n.py_file), encoding="utf-8", mode="at") as py_file_at:
        for k, v in settings.items():
            if py_file_at.writable():
                if n.str or n.regex or not(n.str or n.int or n.regex):
                    new_line = STR_SNIPPET.format(**{"name": k.upper(),
                                                     "option": k,
                                                     "fallback":
                                                     repr(v),
                                                     "apply":str(n.apply)})
                    py_file_at.write(new_line)
                    if n.verbose: 
                        debug(py_file_at, new_line)
                if n.int:
                    new_line = INT_SNIPPET.format(**{"name": k.upper(),
                                                     "option": k,
                                                     "fallback":
                                                     str(v)})
                    py_file_at.write(new_line)
                    if n.verbose: 
                        debug(py_file_at, new_line)
            else: 
                print("The file is not writable.")

if __name__ == "__main__":
    n = parse()
    if arguments_valid(n):
        write(n)
    else:
        print("An option can only have one type.")


