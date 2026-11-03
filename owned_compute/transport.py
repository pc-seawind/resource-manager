"""Owned SSH routes, infrastructure transport only; allocation happens first."""
import shlex

HOSTS = {'local': [], 'office': ['office'], 'wsl': ['wsl'],
         'single5090': ['office', '5090'], 'dual5090': ['office', 'Dual5090']}


def argv(host, command):
    result = list(command)
    for target in reversed(HOSTS[host]):
        result = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', target, shlex.join(result)]
    return result
