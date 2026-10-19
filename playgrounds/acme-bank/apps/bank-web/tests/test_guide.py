"""The guide of the playground names the lessons and the buttons of the app: they are checked against the guide itself, when it is next to the app (GUIDE names it
in a container, else ../../guide.md is read). The commands themselves are in test_commands.py."""

import os
import re
import unittest
from pathlib import Path

import commands
import hops

ACTION = re.compile(r"\[([^\]\n]+)\]\(action:([^)\s]*)\)")     # [Leak an IBAN](action:leak-an-iban): the Lab UI draws it as a button that runs the command
STEP = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)


def guide_text() -> str | None:
    """The guide of the playground, when it is next to the app (a checkout) or named by GUIDE (a container that was given it)."""
    folders = Path(__file__).resolve().parents        # next to the app: apps/bank-web/tests/ is three folders under the playground's; in an image, the guide is given
    for path in (os.environ.get("GUIDE"), *(folder / "guide.md" for folder in folders[2:4])):
        if path and Path(path).is_file():
            return Path(path).read_text()
    return None


def quoted(text: str) -> set[str]:
    """What a guide puts in bold, in code or in a button: the labels and titles it quotes."""
    return (set(re.findall(r"\*\*([^*\n]+)\*\*", text)) | set(re.findall(r"`([^`\n]+)`", text))
            | {label for label, _ in ACTION.findall(text)})


class TheGuide(unittest.TestCase):
    def setUp(self) -> None:
        self.guide = guide_text()
        if self.guide is None:
            self.skipTest("the guide is not next to the app (a container built from this folder alone): run this from a checkout, or set GUIDE")

    def test_the_steps_of_the_guide_are_numbered_from_1_without_a_gap(self):
        steps = [int(number) for number, _ in STEP.findall(self.guide)]
        self.assertEqual(steps, list(range(1, len(steps) + 1)))

    def test_the_groups_of_commands_are_the_first_steps_of_the_guide_under_the_same_titles(self):
        steps = [(int(number), title.strip()) for number, title in STEP.findall(self.guide)]
        self.assertEqual([(group.id, group.title) for group in commands.GROUPS], steps[:len(commands.GROUPS)])

    def test_every_button_of_the_guide_is_a_command_of_the_app_under_its_own_label(self):
        """A command is named in the guide by a standard Markdown link, `[label](action:id)`, which the Lab UI draws as a button that runs it in the app. The id is
        the app's and the text is the label of that command word for word, so the button of the guide and the button of the app read the same."""
        found = ACTION.findall(self.guide)
        self.assertTrue(found, "the guide has no button")
        for label, id in found:
            self.assertTrue(id in commands.COMMANDS, f"the guide has a button for '{id}': the app has no such command")
            self.assertEqual(label, commands.COMMANDS[id].label, f"the button '{id}' of the guide is not named as the command of the app")

    def test_every_command_of_the_app_has_its_button_in_a_lesson(self):
        start = STEP.search(self.guide).start()
        after = re.search(r"^## (?!\d+\. )", self.guide[start:], re.MULTILINE)      # the numbered steps end at the first section that is not one
        lessons = self.guide[start:start + after.start()] if after else self.guide[start:]
        for id, command in commands.COMMANDS.items():
            self.assertTrue(f"[{command.label}](action:{id})" in lessons, f"no lesson has the button of '{command.label}'")

    def test_a_hop_the_guide_quotes_is_titled_as_the_app_titles_it(self):
        """Behind the answer names each hop from one table (`hops.TITLES`): a bold phrase of the guide that reads like a hop is one of those titles."""
        def pattern(template: str) -> re.Pattern:
            parts = re.split(r"(\{\w+\})", template)
            return re.compile("^" + "".join((rf"(Alice|Bob|Tina|{hops.NOBODY})" if part == "{person}" else r"[a-z_]+" if part == "{name}" else r"[A-Z][A-Za-z ]+" if part == "{team}"
                                             else re.escape(part)) for part in parts) + "$")
        titles = [pattern(template) for template in hops.TITLES.values()]
        for phrase in quoted(self.guide):
            if re.match(rf"(Alice|Bob|Tina|{hops.NOBODY}|Ace|A developer|Hackathon sandbox) (asked|called|got a token|could not finish)\b", phrase):
                self.assertTrue(any(title.match(phrase) for title in titles), f"the guide names a hop '{phrase}': no title of the app reads like it")
