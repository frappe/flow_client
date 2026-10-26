# Copyright (c) 2026, Frappe Technologies and contributors
# License: MIT. See LICENSE

"""A joiner that spells a word is not a joiner that hides one.

THE DEFECT THIS MODULE WAS WRITTEN AGAINST. `_escaped` marks every code point carrying Unicode's
`Default_Ignorable_Code_Point` property, and U+200D ZERO WIDTH JOINER carries it. In Sinhala, Tamil,
Devanagari and every other Indic script the joiner is not decoration: a conjunct is spelled
CONSONANT + VIRAMA + ZWJ + CONSONANT, so `\u0dc1\u0dca\u200d\u0dbb\u0dd3` — the first word of this
company's own country — arrived on the approval card as `\u0dc1\u0dca\\u200d\u0dbb\u0dd3`, six
characters of machine escape dropped into the middle of a word. The defence meant to stop a person
approving something they could not read was making the text unreadable for the people who read it.

WHAT IS ADOPTED, AND FROM WHERE. Two sibling front ends had already decided this and tested it —
`agentq-web/src/features/chat/lib/visibleControls.ts` and its character-for-character twin in
`veyqon-web`, both at `joinsRatherThanHides`: *"a joiner that FOLLOWS a virama is orthography, not
hiding, and is kept."* This module does not invent a policy; it ports one, and then tightens it,
because the front ends' version never looks at what comes AFTER the joiner and so keeps a joiner
with nothing to join.

THE RULE, WHOLE. A joiner — U+200C ZWNJ or U+200D ZWJ — is left as itself, unescaped, only when
every one of these holds:
  1. it is neither the first nor the last code point of the value;
  2. the code point immediately before it is a VIRAMA (canonical combining class 9);
  3. the code point immediately after it is a LETTER (general category L*);
  4. those two neighbours lie in the same 128-code-point aligned block.
Everything else is escaped exactly as it was before: a joiner at either edge, a doubled joiner, a
joiner in a run, a joiner beside a space or a bracket, a joiner between two ordinary letters, and
every other character the escaper has ever marked.

WHY EACH CLAUSE IS THERE, since a rule nobody can justify is a rule the next person will widen:
  - (1) and (3) are the shape of the attack. A joiner with nothing on one side of it is joining
    nothing; it is only hiding. They also dispose of the doubled and the run cases for free, because
    the code point after the first joiner in `VIRAMA ZWJ ZWJ LETTER` is a joiner, which is not a
    letter.
  - (2) is what makes it orthography rather than decoration, and it is READ FROM THE LIBRARY —
    `unicodedata.combining(ch) == 9` is Unicode's own Virama combining class. The front ends write
    out sixteen viramas by hand; measured here on UCD 16.0.0 there are SIXTY-NINE, so their list is
    a strict subset missing fifty-three, which is the same table-drift this whole change is about.
  - (4) is the one clause the front ends do not have at all, and it closes a hole they still carry.
    Without it `SO-000A\u094d\u200dx` — a Latin letter, a Devanagari virama, a joiner, a Latin `x`
    — satisfies every other clause while the joiner forms no conjunct with anything, so it is purely
    hidden. A virama binds the letter beside it in its OWN script.

WHAT THIS DOES NOT DO, SAID PLAINLY. It changes what is DISPLAYED and nothing else. The arguments
the tool receives are the model's own bytes, before and after this change alike, and
`TestTheValueThatRUNSIsUntouched` asserts that through a real approved call rather than by reading
the code.

NOT TOUCHED BY THIS MODULE: `_invoke`, `_resolve_confirmation`, `_confirmation_question` and
`_has_denial` (CLAUDE.md rule 4). `_escaped` gains one branch; no second escaper is created.
"""

from __future__ import annotations

import pathlib
import re
import unicodedata

from frappe.tests import IntegrationTestCase

from flow.lib.agent import _escaped

ZWJ = "\u200d"
ZWNJ = "\u200c"
RTL = "\u202e"  # RIGHT-TO-LEFT OVERRIDE

# Real words, written the way a person writes them. Each is CONSONANT VIRAMA ZWJ CONSONANT ...
SINHALA = "\u0dc1\u0dca\u200d\u0dbb\u0dd3 \u0dbd\u0d82\u0d9a\u0dcf"  # "Sri Lanka"
TAMIL = "\u0b95\u0bcd\u200d\u0bb7"  # the conjunct KSSA
DEVANAGARI = "\u0915\u094d\u200d\u0937"  # the conjunct KSSA


class TestAConjunctSurvivesTheCard(IntegrationTestCase):
	"""T1. The damage, asserted on the exact output — not on "contains a marker"."""

	def test_a_sinhala_word_reaches_the_reader_as_it_was_written(self):
		self.assertEqual(_escaped(SINHALA), SINHALA)

	def test_a_tamil_conjunct_reaches_the_reader_as_it_was_written(self):
		self.assertEqual(_escaped(TAMIL), TAMIL)

	def test_a_devanagari_conjunct_reaches_the_reader_as_it_was_written(self):
		self.assertEqual(_escaped(DEVANAGARI), DEVANAGARI)

	def test_a_zero_width_non_joiner_spells_too(self):
		"""ZWNJ after a virama asks for the SEPARATE form where ZWJ asks for the joined one. Both
		are spelling, so both are exempt, and the front ends' `JOINERS` list says the same."""
		word = "\u0dc1\u0dca\u200c\u0dbb"
		self.assertEqual(_escaped(word), word)


class TestTheControlsThatMustStillGoRed(IntegrationTestCase):
	"""T1's other half: the cases that were already right and must stay right."""

	def test_a_joiner_with_no_letter_either_side_is_still_escaped(self):
		self.assertEqual(_escaped(ZWJ), "\\u200d")
		self.assertEqual(_escaped(f"paid{ZWJ}unpaid"), "paid\\u200dunpaid")

	def test_a_right_to_left_override_is_still_escaped(self):
		self.assertEqual(_escaped(f"gnp{RTL}exe"), "gnp\\u202eexe")

	def test_ordinary_text_is_still_returned_untouched(self):
		self.assertEqual(_escaped("Sales Order SO-0001"), "Sales Order SO-0001")


class TestAJoinerWithNothingToJoinIsStillMarked(IntegrationTestCase):
	"""T2. Every shape that is not a joiner doing its job. The virama is present in all of them,
	so each one isolates a single clause of the rule rather than the presence of Indic text."""

	def test_a_joiner_at_the_end_of_a_value_is_marked(self):
		self.assertEqual(_escaped("\u0dc1\u0dca\u200d"), "\u0dc1\u0dca\\u200d")

	def test_a_joiner_at_the_start_of_a_value_is_marked(self):
		self.assertEqual(_escaped("\u200d\u0dbb"), "\\u200d\u0dbb")

	def test_a_joiner_before_a_space_is_marked(self):
		self.assertEqual(_escaped("\u0dc1\u0dca\u200d \u0dbb"), "\u0dc1\u0dca\\u200d \u0dbb")

	def test_a_joiner_before_punctuation_is_marked(self):
		self.assertEqual(_escaped("\u0dc1\u0dca\u200d.\u0dbb"), "\u0dc1\u0dca\\u200d.\u0dbb")

	def test_a_doubled_joiner_is_marked_on_both_halves(self):
		self.assertEqual(_escaped("\u0dc1\u0dca\u200d\u200d\u0dbb"), "\u0dc1\u0dca\\u200d\\u200d\u0dbb")

	def test_a_long_run_of_joiners_is_marked_end_to_end(self):
		self.assertEqual(
			_escaped("\u0dc1\u0dca" + ZWJ * 8 + "\u0dbb"), "\u0dc1\u0dca" + "\\u200d" * 8 + "\u0dbb"
		)

	def test_a_joiner_with_no_virama_before_it_is_marked_however_indic_the_letters_are(self):
		self.assertEqual(_escaped("\u0dc1\u200d\u0dbb"), "\u0dc1\\u200d\u0dbb")

	def test_a_virama_from_one_script_does_not_license_a_joiner_before_another(self):
		"""Clause 4, and the hole the two front ends still have. A Devanagari virama sitting on a
		Latin letter forms no conjunct with a Latin `x`; the joiner between them is hiding."""
		self.assertEqual(_escaped("SO-000A\u094d\u200dx"), "SO-000A\u094d\\u200dx")
		self.assertEqual(_escaped("\u0dc1\u0dca\u200d\u0937"), "\u0dc1\u0dca\\u200d\u0937")

	def test_a_joiner_before_a_vowel_sign_is_marked(self):
		"""Clause 3 ON ITS OWN, and the reason it is not redundant. U+0DCF is in the SAME Sinhala
		block as the virama, so clause 4 waves it through; it is a vowel sign and not a letter, and
		VIRAMA + JOINER + VOWEL SIGN spells nothing. The first version of this module had no test
		that failed when clause 3 was deleted — a guard whose failure nobody had watched."""
		self.assertEqual(_escaped("\u0dc1\u0dca\u200d\u0dcf"), "\u0dc1\u0dca\\u200d\u0dcf")

	def test_a_joiner_before_a_second_virama_is_marked(self):
		"""Same block, same category as the character that licensed it, and still not a letter."""
		self.assertEqual(_escaped("\u0dc1\u0dca\u200d\u0dca"), "\u0dc1\u0dca\\u200d\u0dca")

	def test_a_joiner_before_a_digit_of_the_same_script_is_marked(self):
		"""U+0DE6 SINHALA LITH DIGIT ZERO: same block, category Nd. A digit is not a consonant and
		a joiner cannot bind one — this is the shape that hides a difference between two amounts."""
		self.assertEqual(_escaped("\u0dc1\u0dca\u200d\u0de6"), "\u0dc1\u0dca\\u200d\u0de6")

	def test_a_joiner_before_punctuation_of_the_same_script_is_marked(self):
		self.assertEqual(_escaped("\u0dc1\u0dca\u200d\u0df4"), "\u0dc1\u0dca\\u200d\u0df4")

	def test_a_bidi_override_beside_an_exempt_joiner_is_still_marked(self):
		"""The exception is for joiners and reaches nothing else. Here the joiner IS doing its job
		and stays; the override beside it is marked all the same."""
		self.assertEqual(_escaped(RTL + "\u0dc1\u0dca\u200d\u0dbb"), "\\u202e\u0dc1\u0dca\u200d\u0dbb")

	def test_an_override_immediately_after_a_virama_takes_no_exemption_from_it(self):
		self.assertEqual(_escaped("\u0dc1\u0dca\u202e\u0dbb"), "\u0dc1\u0dca\\u202e\u0dbb")

	def test_a_joiner_between_a_virama_and_an_override_is_marked(self):
		self.assertEqual(_escaped("\u0dc1\u0dca\u200d\u202e\u0dbb"), "\u0dc1\u0dca\\u200d\\u202e\u0dbb")


class TestTwoValuesAReaderCannotTellApartStillEscapeDifferently(IntegrationTestCase):
	"""T2's whole point: the exception must not dissolve the defence it is an exception to.

	THE FIRST VERSION OF THIS CLASS COULD NOT GO RED, and a reviewer caught it by mutation. It
	asserted that two values never produce the same STRING — and `_escaped` never deletes a code
	point, so string injectivity is unconditional. With `_spells_rather_than_hides` mutated to
	`return True`, the whole defence removed and every joiner kept raw, all three tests stayed
	green, including one named `keeps "paid" and "paid<ZWJ>" apart` at the moment those two
	displayed identically. CLAUDE.md, in as many words: a gate whose failure mode has never been
	observed is a comment.

	What matters is not that the strings differ. It is that they differ **in characters a renderer
	paints**. `_painted` below is written HERE, in the test, from the note's own §2 table rather
	than imported from the code under test — an inverse supplied by the code under test would agree
	with any escaper, including a broken one.

	AND THE ONE PLACE THAT IS NOT TRUE IS THE EXCEPTION ITSELF, which is why the pairs are in two
	lists. A conjunct joiner is invisible BY DESIGN: `ශ්ර` and `ශ්‍ර`
	differ only by it, and what distinguishes them on screen is that a conformant Sinhala renderer
	draws the second as a touching conjunct and the first as two separate letters. A test cannot see
	a font. So those pairs are named, one by one, as the DECLARED COST of the exception — and every
	other pair must still paint differently.
	"""

	@staticmethod
	def _invisible() -> frozenset[str]:
		"""Every code point §2 of the note names, read from the note.

		A HAND-WRITTEN FIFTEEN WAS NOT ENOUGH, and the comment that stood here claimed it was "one
		of two independent statements meeting in the middle" when nothing compared them. The table
		has 4174 members; a widening that exempted a variation selector or a tag character would
		have gone unstripped and uncaught. The note is parsed instead — it is the one writing of
		the rule, and `test_s24` is what keeps it true against the engine's own table.
		"""
		note = (
			pathlib.Path(__file__).resolve().parents[2]
			/ "brain"
			/ "40-architecture"
			/ "the-invisible-character-rule.md"
		).read_text(encoding="utf-8")
		block = re.search(r"^```default-ignorable-ranges\n(.*?)^```$", note, re.DOTALL | re.MULTILINE)
		assert block, "the note has no ranges block"
		out: set[str] = set()
		for line in block.group(1).splitlines():
			if not line.strip():
				continue
			low, high = line.split()[:2]
			out.update(chr(cp) for cp in range(int(low[2:], 16), int(high[2:], 16) + 1))
		return frozenset(out)

	# Pairs that must still differ in what a reader can SEE.
	PAINTED_PAIRS = (
		("paid", f"paid{ZWJ}"),
		("SO-0001", "SO-0001\u200d"),
		("SO-0001", "SO-0001\u3164"),
		("paid", f"paid{ZWJ}unpaid"),
		("\u0dc1\u0dca\u200d\u0dbb", "\u0dc1\u0dca\u200d\u200d\u0dbb"),
		# Thai carries a combining class 9 mark and NO joiner orthography, so a joiner after it is
		# inert: it paints nothing and forms nothing. The reviewer's F2, and the reason the rule is
		# confined to the ten Brahmi-derived blocks rather than to a combining class.
		("\u0e01\u0e3a\u0e02", "\u0e01\u0e3a\u200d\u0e02"),
		("\u0eba\u0e81", "\u0eba\u200d\u0e81"),
		("\u2d31\u2d7f\u2d30", "\u2d31\u2d7f\u200d\u2d30"),
		("\u1000\u103a\u1001", "\u1000\u103a\u200d\u1001"),
	)

	# Pairs whose only difference IS a conjunct joiner. THESE ARE EXAMPLES OF THE COST, NOT A
	# CENSUS OF IT, and the first version of this class claimed otherwise — a reviewer showed that
	# the Sinhala ZWNJ pair (which is the note's own §5 "kept" vector, and worse than either pair
	# below: ZWNJ after AL-LAKUNA asks for the separated form Sinhala already draws by default, so
	# it is inert in EVERY conformant font) and a Tamil pair with no ligature both pay it and were
	# in neither list. The true size of the cost is every (virama, letter) pair the twelve viramas
	# admit, minus the ones a font actually forms — which is a font question, not a test question.
	CONJUNCT_PAIRS = (
		("\u0dc1\u0dca\u0dbb", "\u0dc1\u0dca\u200d\u0dbb"),
		("\u0915\u094d\u0937", "\u0915\u094d\u200d\u0937"),
		("\u0dc1\u0dca\u0dbb", "\u0dc1\u0dca\u200c\u0dbb"),  # the ZWNJ case, inert in every font
		("\u0b95\u0bcd\u0baa", "\u0b95\u0bcd\u200d\u0baa"),  # Tamil k+p forms no ligature anywhere
	)

	def _painted(self, text: str) -> str:
		invisible = self._invisible()
		return "".join(ch for ch in text if ch not in invisible)

	def test_the_stripper_itself_strips(self):
		"""The positive control for `_painted`. Without it, a stripper that removed nothing would
		make every assertion below pass."""
		self.assertEqual(self._painted(f"a{ZWJ}b"), "ab")
		self.assertEqual(self._painted("ab"), "ab")
		self.assertEqual(len(self._invisible()), 4174)  # the whole table, not a sample of it
		self.assertEqual(self._painted("a\ufe0fb\U000e0101c"), "abc")  # a selector and a tag

	def test_no_two_of_them_paint_alike(self):
		"""The assertion the mutated code fails: with the exception widened to everything, `paid`
		and `paid` + ZWJ both come through raw and paint the same four letters."""
		for left, right in self.PAINTED_PAIRS:
			with self.subTest(left=repr(left), right=repr(right)):
				self.assertNotEqual(left, right)  # positive control: two values, really
				self.assertNotEqual(
					self._painted(_escaped(left)),
					self._painted(_escaped(right)),
					"two values a reader cannot tell apart",
				)

	def test_the_conjunct_pairs_are_the_declared_cost_and_are_kept_short(self):
		"""These DO paint alike once the joiner is stripped, and that is the exception working — for
		the first two, because a conformant renderer draws the conjunct and the non-conjunct
		differently, which no test can see. For the last two it is NOT working: nothing draws them
		differently, and they are here because a claim that they did not exist was false.

		There is deliberately NO assertion on the length of this list. The first version had one,
		under a docstring saying the cost "cannot grow without somebody writing the new pair down".
		Nothing forced that, and two pairs inside the range were already paying it unlisted. A
		count that nothing enforces is worse than no count: it reads as a bound."""
		for left, right in self.CONJUNCT_PAIRS:
			with self.subTest(left=repr(left)):
				self.assertEqual(self._painted(_escaped(left)), self._painted(_escaped(right)))

	def test_no_two_of_them_escape_alike_either(self):
		"""The weaker string property, kept because it is still true and still worth pinning."""
		for left, right in self.PAINTED_PAIRS + self.CONJUNCT_PAIRS:
			with self.subTest(left=repr(left)):
				self.assertNotEqual(_escaped(left), _escaped(right))

	def test_a_value_cannot_forge_the_escape_of_another(self):
		"""The backslash is escaped, so the six literal characters `\\u200d` can never be mistaken
		for the escape the card emits for a real joiner."""
		self.assertEqual(_escaped("\\u200d"), "\\\\u200d")

	def test_the_exemption_is_injective_over_a_swept_alphabet(self):
		alphabet = ("\u0dc1", "\u0dca", ZWJ, ZWNJ, "\u0dbb", " ")
		seen: dict[str, str] = {}
		for a in alphabet:
			for b in alphabet:
				for c in alphabet:
					value = a + b + c
					shown = _escaped(value)
					self.assertNotIn(shown, seen, f"{value!r} and {seen.get(shown)!r} display alike")
					seen[shown] = value


class TestTheExceptionIsConfinedToScriptsThatSpellWithIt(IntegrationTestCase):
	"""The reviewer's F2 and F3, as properties rather than examples.

	CLAUSE 2 WAS WRONG AS FIRST WRITTEN. It asked only for canonical combining class 9, which is a
	statement about how a mark reorders — not about whether its script spells conjuncts with a
	joiner. Thai U+0E3A PHINTHU, Lao U+0EBA, Tifinagh U+2D7F, Myanmar U+103A ASAT and Brahmi
	U+1107F NUMBER JOINER all carry it and NONE of them takes a joiner, so the joiner kept after one
	of them painted nothing and formed nothing: two different writes, one set of pixels, and not
	even a quote to say so.

	CLAUSE 4 WAS JUSTIFIED BY A MEASUREMENT OF THE WRONG DIRECTION. §3 measured which conjuncts the
	128-point block test MISSES (false negatives, which are harmless — they escape). Nobody measured
	the false positives, and there were 27 viramas with a letter of a DIFFERENT script inside their
	own block: U+2D7F TIFINAGH + U+2D00 GEORGIAN, U+A953 REJANG + U+A960 HANGUL, U+10A3F KHAROSHTHI
	+ U+10A60 OLD SOUTH ARABIAN, and so on — exactly the cross-script shape clause 4 was invented to
	refuse.

	Both are closed by the same narrowing: the exception applies only to a virama in U+0900..U+0DFF,
	the ten Brahmi-derived blocks whose joiner orthography the Unicode Standard actually documents.
	Measured 29 Sep 2026 on UCD 16.0.0 and asserted below: twelve viramas, zero mixed blocks, zero
	cross-script false positives.
	"""

	INDIC_LOW, INDIC_HIGH = 0x0900, 0x0DFF

	def _viramas(self) -> list[int]:
		return [cp for cp in range(0x110000) if unicodedata.combining(chr(cp)) == 9]

	def _script(self, cp: int) -> str:
		return unicodedata.name(chr(cp), "").split(" ")[0]

	def test_a_combining_class_nine_mark_outside_the_indic_blocks_licenses_nothing(self):
		"""The reviewer's own pairs, asserted one by one."""
		for base, mark, follow, script in (
			(0x0E01, 0x0E3A, 0x0E02, "Thai"),
			(0x0E81, 0x0EBA, 0x0E82, "Lao"),
			(0x2D31, 0x2D7F, 0x2D30, "Tifinagh"),
			(0x1000, 0x103A, 0x1001, "Myanmar ASAT"),
			(0x11005, 0x1107F, 0x11006, "Brahmi NUMBER JOINER"),
			(0x1700, 0x1714, 0x1701, "Tagalog"),
		):
			value = chr(base) + chr(mark) + ZWJ + chr(follow)
			with self.subTest(script=script):
				self.assertEqual(unicodedata.combining(chr(mark)), 9)  # positive control
				self.assertIn("\\u200d", _escaped(value))

	def test_no_virama_licenses_a_letter_of_another_script(self):
		"""The property clause 4 was supposed to have. Every virama, every letter the rule would
		let it license, across the whole of Unicode — the script of the two must be the same."""
		letters = [cp for cp in range(0x110000) if unicodedata.category(chr(cp))[0] == "L"]
		exempted = 0
		for virama in self._viramas():
			for letter in letters:
				if (virama >> 7) != (letter >> 7):
					continue
				value = "x" + chr(virama) + ZWJ + chr(letter)
				if "\\u200d" in _escaped(value):
					continue
				exempted += 1
				self.assertEqual(
					self._script(virama),
					self._script(letter),
					f"U+{virama:04X} licensed U+{letter:04X}",
				)
		self.assertGreater(exempted, 100)  # positive control: it really did exempt things

	def test_the_exception_reaches_exactly_twelve_viramas(self):
		reached = [
			cp
			for cp in self._viramas()
			if "\\u200d" not in _escaped("x" + chr(cp) + ZWJ + chr(cp - 0x30))
			or self.INDIC_LOW <= cp <= self.INDIC_HIGH
		]
		indic = [cp for cp in self._viramas() if self.INDIC_LOW <= cp <= self.INDIC_HIGH]
		self.assertEqual(len(indic), 12)
		self.assertEqual(sorted(set(reached)), indic)

	def test_the_ten_blocks_are_each_one_script(self):
		"""Why clause 4 is exact inside this range and a heuristic outside it."""
		for block in range(self.INDIC_LOW >> 7, (self.INDIC_HIGH >> 7) + 1):
			scripts = {
				self._script(cp)
				for cp in range(block << 7, (block << 7) + 128)
				if unicodedata.category(chr(cp))[0] == "L"
			}
			with self.subTest(block=hex(block << 7)):
				self.assertEqual(len(scripts), 1, scripts)


class TestTheRuleIsReadFromTheLibraryNotCopiedIntoIt(IntegrationTestCase):
	"""A hand-written virama list is a fourth table. `unicodedata` already knows them."""

	# The sixteen the two front ends write out by hand, quoted from `visibleControls.ts`.
	FRONT_END_VIRAMAS = (
		0x094D,
		0x09CD,
		0x0A4D,
		0x0ACD,
		0x0B4D,
		0x0BCD,
		0x0C4D,
		0x0CCD,
		0x0D4D,
		0x0DCA,
		0x0F84,
		0x1039,
		0x103A,
		0x17D2,
		0x1BAA,
		0xA8C4,
	)

	def test_every_virama_the_front_ends_name_is_one_the_library_names(self):
		for cp in self.FRONT_END_VIRAMAS:
			with self.subTest(cp=hex(cp)):
				self.assertEqual(unicodedata.combining(chr(cp)), 9)

	def test_the_library_knows_more_of_them_than_the_front_ends_do(self):
		"""Not a boast: it is why the list is not copied. A hand-written list is a list somebody has
		to keep, and the front ends' is already short by fifty-three."""
		self.assertGreater(
			sum(1 for cp in range(0x110000) if unicodedata.combining(chr(cp)) == 9),
			len(self.FRONT_END_VIRAMAS),
		)

	def test_a_virama_outside_the_front_ends_list_gets_its_conjunct_too(self):
		"""U+0D3C MALAYALAM SIGN CIRCULAR VIRAMA is not among their sixteen and the library knows
		it. Same rule, no new entry — which is the whole argument for reading the class rather than
		typing a list.

		It is a MALAYALAM virama rather than the Chakma one this test used before the reviewer's F2:
		the exception is now confined to U+0900..U+0DFF, so Chakma keeps no exception. That is a
		narrowing with a measurement behind it, not an oversight — see
		`TestTheExceptionIsConfinedToScriptsThatSpellWithIt`."""
		word = "\u0d15\u0d3c\u200d\u0d37"
		self.assertEqual(unicodedata.combining("\u0d3c"), 9)
		self.assertNotIn(0x0D3C, self.FRONT_END_VIRAMAS)
		self.assertEqual(_escaped(word), word)


class TestTheValueThatRUNSIsUntouched(IntegrationTestCase):
	"""A normalisation may change what is DISPLAYED and never what is SENT.

	The whole change above is display-only, and "display-only" is a claim about the other end of the
	call, so it is measured there: a real gated tool, really approved, and the argument the function
	body actually received compared byte for byte with the argument the model produced. Reading
	`_escaped` cannot establish this, because the question is whether anything ELSE consumed its
	output on the way to the tool.

	THE POSITIVE CONTROL is the second test. A value whose joiner is NOT exempt is displayed with
	the escape in it and STILL arrives at the tool raw — so the first test is not passing merely
	because nothing on this path ever changes anything.
	"""

	def _agent_and_tool(self):
		from flow.lib.agent import Agent
		from flow.lib.tool import Tool

		received: list[str] = []

		def note(text: str) -> str:
			received.append(text)
			return "ok"

		gated = Tool(
			name="note",
			description="Write a note.",
			parameters={
				"type": "object",
				"properties": {"text": {"type": "string"}},
				"additionalProperties": False,
				"required": ["text"],
			},
			func=note,
			requires_confirmation=True,
			title="Write Note",
			# The templated body is the one that goes through `_escaped`. The UNtemplated fallback
			# does not, and `TestTheFallbackDumpIsADifferentDefectEntirely` below is why.
			confirm_template="Write {text}.",
		)
		return Agent, gated, received

	def _model(self, text: str):
		from flow.lib.model import ChatResponse, ToolCall

		class Scripted:
			model_id = "openai/gpt-4o-mini"

			def __init__(self, rs):
				self._rs = list(rs)

			def chat(self, messages, tools=None, *, stream=False):
				return self._rs.pop(0)

		usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
		pause = ChatResponse(
			content=None,
			tool_calls=[ToolCall(id="c1", name="note", arguments={"text": text})],
			finish_reason="tool_calls",
			usage=usage,
		)
		done = ChatResponse(content="done", finish_reason="stop", usage=usage)
		return Scripted([pause, done])

	def _run_and_approve(self, text: str):
		Agent, gated, received = self._agent_and_tool()
		agent = Agent(model=self._model(text), tools=[gated])
		paused = agent.run("write it")
		self.assertTrue(paused.paused)
		self.assertEqual(received, [])  # the question was asked before anything ran
		prompt = paused.questions[0].prompt
		agent.resume(paused.messages, {"c1": "Approve"})
		return prompt, received

	def test_an_exempt_joiner_reaches_the_tool_exactly_as_the_model_wrote_it(self):
		prompt, received = self._run_and_approve(SINHALA)
		self.assertEqual(received, [SINHALA])
		self.assertEqual(received[0].encode(), SINHALA.encode())
		self.assertIn(SINHALA, prompt)  # and the reader saw the word, not an escape

	def test_a_marked_joiner_is_marked_on_the_card_and_still_sent_raw(self):
		"""The positive control: display and wire disagree, which is the point of the whole file."""
		hidden = f"paid{ZWJ}unpaid"
		prompt, received = self._run_and_approve(hidden)
		self.assertEqual(received, [hidden])
		self.assertEqual(received[0].encode(), hidden.encode())
		self.assertIn("paid\\u200dunpaid", prompt)
		self.assertNotIn(hidden, prompt)


class TestTheFallbackDumpIsADifferentDefectEntirely(IntegrationTestCase):
	"""FOUND HERE IN RUN 16, RECORDED AS A PIN ON THE DEFECT, AND FIXED IN RUN 17 BY S26.

	`_confirmation_question` built its fallback body as `json.dumps(call.arguments, indent=2,
	default=str)` (`flow/lib/agent.py`), and `json.dumps` defaults to `ensure_ascii=True`. So on
	the commonest card of all — a gated tool with neither a `confirm_prompt` nor a
	`confirm_template` — EVERY non-ASCII character was escaped, not merely the joiner: a Sinhala
	value arrived as twenty-odd backslash-u sequences and a Tamil one likewise. Run 15's fix could
	not reach it, because that dump never passed through `_escaped` at all.

	Run 16 declined to fix it, correctly: `_confirmation_question` is one of the four functions
	CLAUDE.md rule 4 protects and run 16's brief did not name it, and the one-word change was
	unsafe — `ensure_ascii=False` alone would have put a RIGHT-TO-LEFT OVERRIDE straight onto the
	card, because `ensure_ascii=True` was then the only thing escaping it on that path. It wrote
	these two tests to pin the present behaviour and said in as many words that they were "the
	tests that must flip" the day somebody wrote the spec.

	**Run 17's brief is that spec, and this is that flip.** They now assert the opposite, in the
	same shape, so the change is legible as a change rather than as a deletion. What run 16 named
	as the correct fix is the fix that was made: the body is built from `_escaped` — through
	`_readable_arguments`, which reproduces `json.dumps(indent=2)`'s layout so the English card is
	byte-identical — rather than from `ensure_ascii`.

	The whole of the new behaviour, including every guard `ensure_ascii` had been providing by
	accident, lives in `flow/tests/test_s26_the_card_speaks_every_language.py`. These two stay here
	because this is the file the defect was found in, and a finding that leaves no trace where it
	was found is a finding somebody re-finds.
	"""

	def _fallback_body(self, value: str) -> str:
		from flow.lib.agent import _confirmation_question
		from flow.lib.model import ToolCall
		from flow.lib.tool import Tool

		plain = Tool(
			name="note",
			description="Write a note.",
			parameters={"type": "object", "properties": {"text": {"type": "string"}}},
			func=lambda text: "ok",
			requires_confirmation=True,
		)
		call = ToolCall(id="c1", name="note", arguments={"text": value})
		return _confirmation_question(call, plain).prompt

	def test_a_sinhala_value_is_readable_on_an_untemplated_card(self):
		"""Was `test_a_sinhala_value_is_still_unreadable_on_an_untemplated_card`, asserting
		`\\u0dc1` was present and the word was not. Both clauses are now the other way round."""
		body = self._fallback_body(SINHALA)
		self.assertIn(SINHALA, body)
		self.assertNotIn("\\u0dc1", body)

	def test_the_same_card_with_a_sentence_shows_the_word_correctly(self):
		"""Kept unchanged. It was the positive control that made the test above a FINDING rather
		than a fact of life — the templated half of the same question always rendered the word, so
		the dump was what was wrong. It is now the control that the two halves AGREE."""
		from flow.lib.agent import _render_confirm_template

		self.assertEqual(_render_confirm_template("Write {text}.", {"text": SINHALA}), f'Write "{SINHALA}".')

	def test_the_two_halves_of_the_card_now_agree(self):
		"""What the pair above is worth saying once, directly: the sentence and the arguments
		beneath it show the same word the same way."""
		from flow.lib.agent import _render_confirm_template

		sentence = _render_confirm_template("Write {text}.", {"text": SINHALA})
		self.assertIn(SINHALA, sentence)
		self.assertIn(SINHALA, self._fallback_body(SINHALA))


class TestTheCapDoesNotUndoTheException(IntegrationTestCase):
	"""The reviewer's F1, and it was the worst of the findings.

	`flow/tools/builtins.py` `_for_display` escapes and caps in one pass, and it did so by calling
	`escape_for_display(ch)` on ONE CHARACTER AT A TIME. A one-character string has no character
	before or after it, so clause 1 refused every joiner unconditionally and the exception was
	STRUCTURALLY UNREACHABLE on that path — which is the path the six shipped write builtins use,
	i.e. where production write confirmations actually come from. `_escaped` was fixed and the card
	a person sees was not.

	The fix is that the decision is taken over the WHOLE value once, and the cap then walks the
	per-character escapes that decision produced. `escape_for_display_at` is that decision, exposed
	under a name the tools module can use, so there is still exactly one rule.
	"""

	def _for_display(self, value, limit=None):
		from flow.tools.builtins import _for_display

		return _for_display(value) if limit is None else _for_display(value, limit)

	def test_the_write_builtins_show_a_sinhala_word_as_a_word(self):
		self.assertEqual(self._for_display(SINHALA), f'"{SINHALA}"')

	def test_a_field_value_in_a_create_body_keeps_its_conjunct(self):
		"""Through the real caller, not the helper: `_summarize_values` is what the body shows."""
		from flow.tools.builtins import _summarize_values

		self.assertIn(SINHALA, _summarize_values({"description": SINHALA}))

	def test_a_field_NAME_keeps_its_conjunct_too(self):
		from flow.tools.builtins import _summarize_values

		self.assertIn(SINHALA, _summarize_values({SINHALA: "x"}))

	def test_a_joiner_that_hides_is_still_marked_on_that_path(self):
		"""The control. The cap path must not have become permissive."""
		self.assertEqual(self._for_display(f"paid{ZWJ}unpaid"), '"paid\\u200dunpaid"')

	def test_a_value_cut_off_by_the_cap_still_states_its_true_length(self):
		"""And the exception must not move the cap: the count is measured on the raw value and the
		quote still closes before it."""
		shown = self._for_display(SINHALA, 6)
		self.assertTrue(shown.startswith('"'), shown)
		self.assertIn(f"({len(SINHALA)} characters in all)", shown)

	def test_a_joiner_at_the_very_edge_of_the_cap_is_not_exempted_by_accident(self):
		"""The cut is in the DISPLAY, never in the decision: a conjunct whose joiner falls past the
		cap must still have been judged against the whole value, not against the prefix."""
		long_word = "\u0dc1\u0dca\u200d\u0dbb" * 40
		self.assertNotIn("\\u200d", self._for_display(long_word, 200))


class TestTheCutItselfCannotLeaveAJoinerJoiningNothing(IntegrationTestCase):
	"""The reviewer's second pass. A joiner is kept because of what FOLLOWS it — and the cap can
	put what follows it on the other side of the cut, leaving an unescaped joiner as the last
	painted character inside the quote. That is clause 1's own shape, readmitted by the capping
	caller rather than by the rule."""

	def _for_display(self, value, limit):
		from flow.tools.builtins import _for_display

		return _for_display(value, limit)

	def test_a_conjunct_cut_immediately_after_its_joiner_shows_the_joiner_escaped(self):
		shown = self._for_display("\u0dc1\u0dca\u200d\u0dbb\u0dd3", 3)
		self.assertIn("\\u200d", shown)
		self.assertNotIn("\u200d", shown.split('"')[1])

	def test_the_same_for_a_non_joiner(self):
		shown = self._for_display("\u0dc1\u0dca\u200c\u0dbb", 3)
		self.assertIn("\\u200c", shown)

	def test_a_cut_that_does_not_land_on_a_joiner_is_untouched(self):
		"""The control: the fix must not escape a joiner that is still doing its job."""
		shown = self._for_display("\u0dc1\u0dca\u200d\u0dbb\u0dd3", 4)
		self.assertNotIn("\\u200d", shown)
		self.assertIn("\u0dc1\u0dca\u200d\u0dbb", shown)
