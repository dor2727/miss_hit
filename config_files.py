#!/usr/bin/env python3
##############################################################################
##                                                                          ##
##          MATLAB Independent, Small & Safe, High Integrity Tools          ##
##                                                                          ##
##              Copyright (C) 2019-2020, Zenuity AB                         ##
##                                                                          ##
##  This file is part of MISS_HIT.                                          ##
##                                                                          ##
##  MATLAB Independent, Small & Safe, High Integrity Tools (MISS_HIT) is    ##
##  free software: you can redistribute it and/or modify it under the       ##
##  terms of the GNU General Public License as published by the Free        ##
##  Software Foundation, either version 3 of the License, or (at your       ##
##  option) any later version.                                              ##
##                                                                          ##
##  MISS_HIT is distributed in the hope that it will be useful,             ##
##  but WITHOUT ANY WARRANTY; without even the implied warranty of          ##
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           ##
##  GNU General Public License for more details.                            ##
##                                                                          ##
##  You should have received a copy of the GNU General Public License       ##
##  along with MISS_HIT. If not, see <http://www.gnu.org/licenses/>.        ##
##                                                                          ##
##############################################################################

import os
import re
from copy import deepcopy

import m_lexer
import config
from errors import ICE, Error, Location


CONFIG_FILENAMES = ["miss_hit.cfg", ".miss_hit"]

CONFIG_TREE = {}


class Config_Parser:
    def __init__(self, mh, config_file):
        self.filename = config_file
        self.dirname = os.path.dirname(config_file)
        self.lexer = m_lexer.MATLAB_Lexer(mh, self.filename)
        self.lexer.set_config_file_mode()
        self.mh = mh

        # pylint: disable=invalid-name
        self.ct = None
        self.nt = None
        # pylint: enable=invalid-name

        self.next()

    def next(self):
        self.ct = self.nt
        self.nt = self.lexer.token()

        while self.nt:
            # Skip comments
            while self.nt and self.nt.kind == "COMMENT":
                self.nt = self.lexer.token()

            # Join new-lines
            if (self.nt and
                self.ct and
                self.nt.kind == "NEWLINE" and
                self.ct.kind == "NEWLINE"):
                self.nt = self.lexer.token()
            else:
                break

    def match(self, kind, value=None):
        self.next()
        if self.ct is None:
            self.mh.error(Location(self.lexer.filename),
                          "expected %s, reached EOF instead" % kind)
        elif self.ct.kind != kind:
            self.mh.error(self.ct.location,
                          "expected %s, found %s instead" % (kind,
                                                             self.ct.kind))
        elif value and self.ct.value != value:
            self.mh.error(self.ct.location,
                          "expected %s(%s), found %s(%s) instead" %
                          (kind, value, self.ct.kind, self.ct.value))

    def match_eof(self):
        self.next()
        if self.ct is not None:
            self.mh.error(self.ct.location,
                          "expected end of file, found %s instead" %
                          self.ct.kind)

    def peek(self, kind, value=None):
        if self.nt and self.nt.kind == kind:
            if value is None:
                return True
            else:
                return self.nt.value == value
        else:
            return False

    def parse_file(self, cfg):
        while self.nt:
            if self.nt.kind == "NEWLINE":
                self.match("NEWLINE")
            else:
                self.match("IDENTIFIER")
                t_key = self.ct
                key = self.ct.value
                value = None
                self.match("COLON")

                if key == "enable_rule":
                    self.match("STRING")
                    value = self.ct.value
                    if value not in config.STYLE_RULES:
                        self.mh.error(self.ct.location,
                                      "unknown rule")
                        # TODO: Use difflib to find a likely one

                elif key not in cfg:
                    self.mh.error(t_key.location,
                                  "unknown option %s" % key)

                elif isinstance(cfg[key], int):
                    self.match("NUMBER")
                    try:
                        value = int(self.ct.value)
                    except ValueError:
                        self.mh.error(self.ct.location,
                                      "%s option requires an integer" % key)

                elif isinstance(cfg[key], bool):
                    self.match("NUMBER")
                    if self.ct.value in ("0", "1"):
                        value = self.ct.value == "1"
                    else:
                        self.mh.error(self.ct.location,
                                      "boolean option %s requires 0 or 1" %
                                      key)

                elif isinstance(cfg[key], set):
                    self.match("STRING")
                    value = self.ct.value

                    if key == "exclude_dir":
                        if os.path.basename(value) != value or \
                           not os.path.isdir(os.path.join(self.dirname,
                                                          value)):
                            self.mh.error(self.ct.location,
                                          "must be a valid local directory")

                    elif key == "suppress_rule":
                        if value not in config.STYLE_RULES:
                            self.mh.error(self.ct.location,
                                          "unknown rule")
                            # TODO: Use difflib to find a likely one

                elif isinstance(cfg[key], str):
                    self.match("STRING")
                    value = self.ct.value

                    if key.startswith("regex"):
                        # If this is supposed to be a regex, we can
                        # check in advance if it compiles or not. On
                        # failure we can feed back the error using our
                        # own error system.
                        try:
                            re.compile(value)
                        except re.error as err:
                            loc = deepcopy(self.ct.location)
                            if err.colno is not None:
                                loc.col_start += err.colno
                                loc.col_end = loc.col_start
                            self.mh.error(loc, err.msg)

                if self.nt:
                    self.match("NEWLINE")
                else:
                    self.match_eof()

                if key == "enable_rule":
                    if value in cfg["suppress_rule"]:
                        cfg["suppress_rule"].remove(value)
                elif isinstance(cfg[key], set):
                    cfg[key].add(value)
                else:
                    cfg[key] = value


def load_config(mh, cfg_file, cfg):
    assert isinstance(cfg_file, str)
    assert os.path.isfile(cfg_file)
    assert isinstance(cfg, dict)

    rel_name = os.path.relpath(cfg_file)

    try:
        mh.register_file(rel_name)
        parser = Config_Parser(mh, rel_name)
        parser.parse_file(cfg)
        # Now that we have parsed the file, we should remove it again
        # from the list of files known to the error handler
        mh.unregister_file(rel_name)
    except Error:
        mh.summary_and_exit()


def register_tree(mh, dirname, options):
    assert isinstance(dirname, str)
    assert os.path.isdir(dirname)
    assert dirname == os.path.abspath(dirname)

    def register_parent(dirname, find_roots):
        if dirname in CONFIG_TREE:
            return

        # Stop if we reach the root filesystem or a .git directory
        parent = os.path.dirname(dirname)
        if find_roots:
            is_root = parent == dirname
        else:
            is_root = False

        if not is_root:
            register_parent(parent, find_roots)
            CONFIG_TREE[parent]["children"].add(dirname)

        config_name = None
        if not options.ignore_config:
            for filename in CONFIG_FILENAMES:
                if os.path.isfile(os.path.join(dirname, filename)):
                    if config_name is None:
                        config_name = filename
                    else:
                        mh.register_file("directory " +
                                         os.path.relpath(dirname))
                        mh.error(Location("directory " +
                                          os.path.relpath(dirname)),
                                 "cannot have both a %s and %s config file" %
                                 (config_name, filename))

        CONFIG_TREE[dirname] = {
            "children"   : set(),
            "subtree"    : False,
            "has_config" : config_name,
            "root"       : is_root,
            "parent"     : None if is_root else parent
        }

    def register_subtree(dirname):
        if CONFIG_TREE[dirname]["subtree"]:
            return

        CONFIG_TREE[dirname]["children"] = set(
            os.path.join(dirname, d)
            for d in os.listdir(dirname)
            if (os.path.isdir(os.path.join(dirname, d)) and
                os.access(os.path.join(dirname, d), os.R_OK))
        )

        for child in CONFIG_TREE[dirname]["children"]:
            register_parent(child, find_roots=False)
            register_subtree(child)

        CONFIG_TREE[dirname]["subtree"] = True

    register_parent(dirname, find_roots=True)
    register_subtree(dirname)


def build_config_tree(mh, defaults, cmdline_options):
    # Construct basic default options
    root_config = deepcopy(config.BASE_CONFIG)
    root_config.update(defaults)

    # Find root of config tree
    roots = [d for d in CONFIG_TREE if CONFIG_TREE[d]["root"]]
    if len(roots) == 0:
        raise ICE("could not find any project or filesystem root")
    elif len(roots) == 1:
        project_root = roots[0]
    elif len(roots) > 1:
        raise ICE("found multiple roots: %s" % ", ".join(roots))

    parse_config = not cmdline_options.ignore_config

    def merge_command_line(cfg):
        # Overwrite with options from the command-line
        if cmdline_options.line_length:
            cfg["line_length"] = cmdline_options.line_length
        if cmdline_options.file_length:
            cfg["file_length"] = cmdline_options.file_length
        if cmdline_options.tab_width:
            cfg["tab_width"] = cmdline_options.tab_width
        if cmdline_options.copyright_entity:
            cfg["copyright_entity"] = set(cmdline_options.copyright_entity)
        if cmdline_options.octave:
            cfg["octave"] = cmdline_options.octave

    def build(node, exclude=False):
        if CONFIG_TREE[node]["root"]:
            # First we set up basic config. For roots this is a copy
            # of the default config.
            CONFIG_TREE[node]["config"] = deepcopy(root_config)
            merge_command_line(CONFIG_TREE[node]["config"])
        else:
            # For non-roots we copy the parent config.
            parent_node = CONFIG_TREE[node]["parent"]
            parent_config = CONFIG_TREE[parent_node]["config"]
            CONFIG_TREE[node]["config"] = deepcopy(parent_config)

            # We reset the exclude_dir field as it makes no sense to
            # propagate it.
            CONFIG_TREE[node]["config"]["exclude_dir"] = set()

        # We now have basic configuration for this node. If we're in
        # exclude mode we just set enable to false for this node.
        if exclude:
            CONFIG_TREE[node]["config"]["enable"] = False

        # Otherwise we process any config file
        elif CONFIG_TREE[node]["has_config"] and parse_config:
            load_config(mh,
                        os.path.join(node, CONFIG_TREE[node]["has_config"]),
                        CONFIG_TREE[node]["config"])
            merge_command_line(CONFIG_TREE[node]["config"])

        # Finally, loop over all children to continue building the
        # tree.
        for child in CONFIG_TREE[node]["children"]:
            to_exclude = (exclude or
                          os.path.basename(child) in
                          CONFIG_TREE[node]["config"]["exclude_dir"])
            build(child, exclude=to_exclude)

    build(project_root, exclude=False)


def get_config(filename):
    dirname = os.path.dirname(os.path.abspath(filename))

    if dirname not in CONFIG_TREE:
        if not os.path.isdir(dirname):
            hint = " (note: this is not a directory)"
        else:
            hint = ""
        raise ICE("%s: expected %s to be in configuration tree%s" % (filename,
                                                                     dirname,
                                                                     hint))

    return CONFIG_TREE[dirname]["config"]