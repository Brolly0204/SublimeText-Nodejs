import os
import re

import sublime
import sublime_plugin

import psutil
import shellenv

from .nodejs_debug import debug, info
from .nodejs_nvm import Nvm
from .nodejs_command_thread import CommandThread, run_os_command


class NodeCommand(sublime_plugin.TextCommand):

    def run_command(self, command, callback=None, show_status=True,
                    filter_empty_args=True, **kwargs):

        shell = False

        if filter_empty_args:
            command = [arg for arg in command if arg]

        if 'working_dir' not in kwargs:
            kwargs['working_dir'] = self.get_working_dir()
        s = sublime.load_settings("Nodejs.sublime-settings")

        if s.get('save_first') and self.active_view() and self.active_view().is_dirty():
            self.active_view().run_command('save')

        if command[0] == 'node':
            if s.get('node_command'):
                self.insert_command_with_args(s.get('node_command'), command)
            if s.get('node_path'):
                kwargs['env'] = {"NODE_PATH": str(s.get('node_path'))}

        if command[0] == 'npm' and s.get('npm_command'):
            self.insert_command_with_args(s.get('npm_command'), command)

        debug("NodeCommand: run_command: command", command)

        # update paths for searching executables
        kwargs['env'] = {}
        kwargs['env'].update({'PATH': shellenv.get_env()[1]['PATH']})

        if not callback:
            callback = self.generic_done

        if os.name == 'nt':
            shell = True
            # doing exception for debugger commands to be able
            # get PID of node.exe on Windows not cmd.exe
            debug("NodeCommand: run_command: class name", self.__class__.__name__)
            if self.__class__.__name__.lower().find("drun") != -1:
                shell = False

        kwargs['shell'] = shell
        debug("NodeCommand: run_command: kwargs", kwargs)

        thread = CommandThread(command, callback, **kwargs)
        thread.start()

        if show_status:
            message = kwargs.get('status_message', False) or ' '.join(command)
            sublime.status_message(message)

    def insert_command_with_args(self, cmd_as_string, command_array):
        cmds = reversed(cmd_as_string.split())
        command_array.pop(0)

        for c in cmds:
            command_array.insert(0, c)
        debug("NodeCommand: insert_command_with_args: command_array", command_array)

    def run_os_command(self, cmd):
        return run_os_command(cmd)

    def node_version(self):
        cmd = ['node', '--version']
        version = self.run_os_command(cmd)

        debug('node_version: raw', version)

        version = int(re.findall('v(\d+)', version)[0])
        debug('node_version: int', version)

        return version

    def generic_done(self, result):
        if not result.strip():
            return
        self.panel(result)

    def _output_to_view(self, output_file, output, clear=False, syntax="Packages/JavaScript/JavaScript.tmLanguage", **kwargs):
        output_file.set_syntax_file(syntax)

        args = {
            'output': output,
            'clear': clear
        }
        output_file.run_command('node_scratch_output', args)

    def _is_output_panel_exist(self):
        return 'output.nodejs' in self.get_window().panels()


    def scratch(self, output, title=False, position=None, **kwargs):
        scratch_file = self.get_window().new_file()
        if title:
            scratch_file.set_name(title)
        scratch_file.set_scratch(True)
        self._output_to_view(scratch_file, output, **kwargs)
        scratch_file.set_read_only(True)
        if position:
            sublime.set_timeout(
                lambda: scratch_file.set_viewport_position(position), 0)
        return scratch_file

    def panel(self, output, **kwargs):
        self.output_view = self.get_window().create_output_panel("nodejs")
        self.output_view.set_read_only(False)
        self._output_to_view(self.output_view, output, clear=True, **kwargs)
        self.output_view.set_read_only(True)
        self.get_window().run_command("show_panel", {"panel": "output.nodejs"})

    def quick_panel(self, *args, **kwargs):
        self.get_window().show_quick_panel(*args, **kwargs)


class NodeWindowCommand(NodeCommand, sublime_plugin.WindowCommand):
    """
    A base for all node commands that work with the entire repository
    """

    def active_view(self):
        return self.window.active_view()

    def _active_file_name(self):
        view = self.active_view()
        if view and view.file_name() and len(view.file_name()) > 0:
            return view.file_name()

    def is_enabled(self):
        return True  # A better test should be made. Fx. is this a js file?

    def get_file_name(self):
        return ''

    # If there is a file in the active view use that file's directory to
    # search for the Git root.  Otherwise, use the only folder that is
    # open.
    def get_working_dir(self):
        file_name = self._active_file_name()
        if file_name:
            return os.path.dirname(file_name)
        else:
            return self.window.folders()[0]

    def get_window(self):
        return self.window


class NodeTextCommand(NodeWindowCommand, sublime_plugin.TextCommand):
    """
    A base for all node commands that work with the file in the active view
    """

    def run(self, edit, user_input=None):
        """
        Base run method
        """
        if user_input:
            self.on_input(user_input)
        else:
            self._input_panel = self.get_window().show_input_panel(
                "Arguments", "", self.on_input, None, None)

    def active_view(self):
        return self.view

    def is_relevant_file(self):
        return sublime.active_window().active_view().scope_name(
            sublime.active_window().active_view().sel()[0].begin()).find('source.js') != -1

    def is_enabled(self):
        return self.is_relevant_file()

    def get_file_name(self):
        return os.path.basename(self.view.file_name())

    def get_working_dir(self):
        return os.path.dirname(self.view.file_name())

    def get_window(self):
        # Fun discovery: if you switch tabs while a command is working,
        # self.view.window() is None. (Admittedly this is a consequence
        # of my deciding to do async command processing... but, hey,
        # got to live with that now.)
        # I did try tracking the window used at the start of the command
        # and using it instead of view.window() later, but that results
        # panels on a non-visible window, which is especially useless in
        # the case of the quick panel.
        # So, this is not necessarily ideal, but it does work.
        return self.view.window() or sublime.active_window()
