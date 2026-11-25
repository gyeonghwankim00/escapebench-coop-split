"""Opt-in presentation diagnostics, derived only from the current observation.

No engine/parser changes, hidden state, valid-solution hints, or auto-correction.
"""
from copy import deepcopy
import re

INTERFACES = ('original', 'move_labels', 'action_labels')


def present(messages, condition, interface='original'):
    if interface == 'original':
        return messages
    if interface not in INTERFACES:
        raise ValueError(interface)
    result = deepcopy(messages)
    user = next(m for m in reversed(result) if m['role'] == 'user')
    current = user['content'].rsplit('Now you need to act on', 1)[-1]
    moves = re.findall(r'^<interactable scene> (.*?): It leads to ', current, re.M)
    lines = ['Action-format reference for the CURRENT observation only:',
             'Use the exact move calls below. Do not include quotation marks or the destination explanation.']
    lines += [f'- move({name})' for name in moves] or ['- No move action is currently listed.']
    if interface == 'action_labels':
        items = re.findall(r'^<interactable item> (.+)$', current, re.M)
        bag = re.findall(r'^<applicable tool> (.*?): ', current, re.M)
        lines += ['Scene objects are not automatically owned. Seeing/uncovering a tool does not collect it.',
                  'Use click on a visible tool to try collecting it; check the feedback and updated bag.',
                  'Current scene click calls (no claim that any will solve a puzzle):']
        lines += [f'- click({name})' for name in items] or ['- None listed.']
        lines += ['Owned tools in your CURRENT bag: ' + (', '.join(bag) or '(empty)'),
                  'apply uses a tool from this bag on a current scene item.',
                  'craft uses two tools already in this bag. It does not use a tool still in the scene.']
        if condition == 'coop':
            lines += ['give transfers an owned tool to your partner; it does not collect or use the tool.',
                      'Current give calls (not recommendations to send these tools):']
            lines += [f'- give({name})' for name in bag] or ['- None: your bag is empty.']
    user['content'] += '\n\n' + '\n'.join(lines) + '\nRespond with Thought: ... and Action: ... as instructed.\n'
    return result
