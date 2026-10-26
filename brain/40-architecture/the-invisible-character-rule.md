---
type: architecture
status: current
measured: 2026-09-29
unicode: 16.0.0
---
# The invisible-character rule — written once, so four copies can be checked against it

THE PROBLEM THIS NOTE EXISTS FOR. The same Unicode rule is written out **four times independently**
across this estate, and on 28 September 2026 a consolidation found that **three of the four were
wrong** — each in a different way. Nothing can be shared between the four repositories, so the only
remaining defence is that the rule is written down ONCE, in full, with the reason for every clause,
and that each copy is measured against the writing. `flow/tests/test_s24_one_rule_four_copies.py`
parses **this file** and fails if either copy in this repository has drifted from it.

If you are changing one copy, change this note first. If this note and a copy disagree, this note
is what the test believes.

## 0. WHERE THE FOUR COPIES ARE

| # | repository | file | how it states the property | joiner exception |
|---|---|---|---|---|
| 1 | `veyqon-flow` (this one) | `flow/lib/agent.py` — `_DEFAULT_IGNORABLE_RANGES`, `_paints_nothing`, `_escaped` | 17 hand-written ranges, because `unicodedata` does not expose the property | **yes**, since 29 Sep 2026 |
| 2 | `veyqon-flow` (this one) | `frontend/src/lib/display.js` — `CONTROL_OR_SEPARATOR`, `escapeForDisplay` | native `\p{Default_Ignorable_Code_Point}` | **yes**, since 29 Sep 2026 |
| 3 | `q_flow_tools` | the tool-side escaper — **OUT OF SCOPE, another lane owns that tree** | 17 hand-written ranges, a copy of #1 | **no — still mangles Sinhala** |
| 4 | `Q-AI` (`agentq-web` and `veyqon-web`, character-for-character twins) | `src/features/chat/lib/visibleControls.ts` | an explicit character class, NOT the property | yes, and it is where ours came from |
| 5 | `q-ai-mobile` | `veyqon-mobile/src/features/chat/lib/display.ts` | native `\p{Default_Ignorable_Code_Point}` | **no, deliberately — and it mangles Sinhala** |

The consolidation counted four; there are five. It also said "both front ends carry a tested
zero-width-joiner exception", and that is only true of the two web apps: the mobile app is a third
front end that decided the other way, on an argument about EMOJI that does not reach the Indic case.

## 1. WHAT IS ESCAPED — THE THREE TERMS

A character is escaped when **any** of the three holds, with the ordinary space `U+0020` excepted
and the joiner exception of §3 subtracted:

1. **Unicode general category C\*** — Cc control, Cf format, Cn unassigned, Co private use, Cs
   surrogate.
2. **Unicode general category Z\*** — Zs space, Zl line separator, Zp paragraph separator.
3. **`Default_Ignorable_Code_Point`** — "a conformant renderer is entitled to paint nothing here".

WHY ALL THREE, in the order the mistakes were made:
- The rule began as **Cc and Cf only**, the categories that *looked* dangerous. That missed U+2028
  and U+2029, which `str.splitlines` and every layout engine treat as line breaks, so a value could
  still open a line of its own inside the card. Hence the whole of C\* and Z\*, which also takes in
  unassigned code points and lone surrogates, so a later revision of Unicode cannot quietly add a
  new way through.
- Term 3 was **missing**, and a reviewer found it by *measuring the property against the rule*
  rather than by reading the rule. **267 code points carry the property and are in neither C\* nor
  Z\***, so all 267 arrived raw AND UNQUOTED — without even the quote that is the signal something
  was escaped. **Four of them are category `Lo`: LETTERS** (U+115F, U+1160, U+3164, U+FFA0). No
  rule about controls, formats, separators or combining marks was ever going to reach a letter, and
  `SO-0001` beside `SO-0001` + U+3164 is two different writes a reader cannot tell apart.

THE PRICE, which is a decision and not an oversight: the property takes in the variation selectors,
so an argument holding an emoji written with U+FE0F renders quoted. The cost of the other choice is
a class of invisible character judged safe by whoever last thought about it, which is the mistake
the whitelist exists to make impossible.

## 2. TABLE ONE — THE SEVENTEEN RANGES

Copy #1 writes these out because Python's `unicodedata` has no such property. Copies #2 and #5 ask
the regex engine for it instead. Both must agree, which is what
`frontend/tests/displayProperty.spec.js` and the test named at the top assert.

```default-ignorable-ranges
U+00AD  U+00AD      1  SOFT HYPHEN
U+034F  U+034F      1  COMBINING GRAPHEME JOINER
U+061C  U+061C      1  ARABIC LETTER MARK
U+115F  U+1160      2  HANGUL CHOSEONG FILLER … HANGUL JUNGSEONG FILLER — LETTERS that paint nothing
U+17B4  U+17B5      2  KHMER VOWEL INHERENT AQ … AA
U+180B  U+180F      5  MONGOLIAN FREE VARIATION SELECTOR ONE … FOUR
U+200B  U+200F      5  ZERO WIDTH SPACE … RIGHT-TO-LEFT MARK — contains BOTH joiners, see §3
U+202A  U+202E      5  LEFT-TO-RIGHT EMBEDDING … RIGHT-TO-LEFT OVERRIDE — reorders without adding
U+2060  U+206F     16  WORD JOINER … NOMINAL DIGIT SHAPES
U+3164  U+3164      1  HANGUL FILLER — a LETTER that paints nothing
U+FE00  U+FE0F     16  VARIATION SELECTOR-1 … -16 — the declared price, see §1
U+FEFF  U+FEFF      1  ZERO WIDTH NO-BREAK SPACE (BOM)
U+FFA0  U+FFA0      1  HALFWIDTH HANGUL FILLER — a LETTER that paints nothing
U+FFF0  U+FFF8      9  unassigned, reserved as ignorable
U+1BCA0 U+1BCA3     4  SHORTHAND FORMAT LETTER OVERLAP … UP STEP
U+1D173 U+1D17A     8  MUSICAL SYMBOL BEGIN BEAM … END PHRASE
U+E0000 U+E0FFF  4096  tag characters and the variation-selector supplement
```

4174 code points in all.

## 3. THE ONE EXCEPTION — A JOINER THAT SPELLS

U+200D ZERO WIDTH JOINER and U+200C ZERO WIDTH NON-JOINER carry the property, so §1 marks them —
correctly for every script that does not use them. **In Sinhala, Tamil, Devanagari and every other
Indic script a joiner is not decoration. It is spelling.** A conjunct is written

> CONSONANT + VIRAMA + ZWJ + CONSONANT

so `ශ්‍රී ලංකා` is two ordinary words, and marking the joiner inside the first turns it into
`ශ්\u200dරී ලංකා` — six characters of machine escape dropped into the middle of the name of the
country most of the people reading these cards live in.

**THE RULE.** A joiner is kept as itself, unescaped, only when **all four** hold:

| # | clause | the shape it refuses |
|---|---|---|
| 1 | it is at neither edge of the value | a joiner with nothing on one side joins nothing; it can only hide |
| 2 | the code point immediately **before** it is a **virama** (canonical combining class 9) **and lies in U+0900–U+0DFF** | a joiner anywhere else between two letters is the hiding case; and a combining-class-9 mark whose script takes no joiner at all, where the joiner paints nothing AND forms nothing |
| 3 | the code point immediately **after** it is a **letter** (category L\*) | a doubled joiner, a run of them, a joiner before a space, a bracket, a digit, a vowel sign or a second virama |
| 4 | those two neighbours share a **128-code-point aligned block** (`cp >> 7` equal) | `SO-000A` + DEVANAGARI VIRAMA + ZWJ + `x`: clauses 1–3 all hold and the joiner binds nothing |

**CLAUSE 2's RANGE IS NOT DECORATION, AND CLAUSE 4 DEPENDS ON IT.** The first version of this rule
asked only for canonical combining class 9. An adversarial review measured what that admits and
found two separate holes, both now closed by the range:

- **Combining class 9 says how a mark REORDERS, not that its script spells with a joiner.** Thai
  U+0E3A PHINTHU, Lao U+0EBA, Tifinagh U+2D7F (itself a consonant joiner), Myanmar U+103A ASAT (a
  killer, not a stacker), Brahmi U+1107F NUMBER JOINER and the Tagalog/Hanunoo marks all carry it
  and none of them takes a joiner. `กฺข` (U+0E01 U+0E3A U+0E02) and `กฺ‍ข` (the same with U+200D)
  are two different writes that paint the same pixels — and both came through raw AND UNQUOTED, so
  the quote did not fire either. That is the attack the escaper exists to stop, readmitted by its
  own exception.
- **Clause 4 was justified by a measurement of the wrong direction.** The paragraph below measures
  which conjuncts the block test MISSES — false negatives, which are harmless because they escape.
  Nobody had measured the false positives, and **27 viramas across Unicode have a letter of a
  DIFFERENT script inside their own 128-point block**: U+2D7F TIFINAGH would have licensed U+2D00
  GEORGIAN, U+A953 REJANG licensed U+A960 HANGUL CHOSEONG, U+ABED MEETEI MAYEK licensed U+AB80
  CHEROKEE, U+10A3F KHAROSHTHI licensed U+10A60 OLD SOUTH ARABIAN, and so on through Tagalog↔Buhid,
  Sundanese↔Batak, Tai Tham↔Buginese, Chakma↔Mahajani and a dozen more. Every one is the
  cross-script shape clause 4 was invented to refuse.

**Inside U+0900–U+0DFF there are ZERO such pairs.** Each of the ten blocks holds the letters of
exactly one script, so within the range `cp >> 7` **is** the script rather than a proxy for it.
Measured 29 Sep 2026 on UCD 16.0.0 and asserted over the whole of Unicode — not over examples — by
`TestTheExceptionIsConfinedToScriptsThatSpellWithIt` in
`flow/tests/test_s23_a_joiner_inside_a_word.py`.

Clause 3 also disposes of the doubled and run cases for free: the code point after the first joiner
of `VIRAMA ZWJ ZWJ LETTER` is a joiner, which is not a letter.

**WHERE IT CAME FROM AND WHERE IT DIVERGES.** Copy #4 decided this first and tested it
(`joinsRatherThanHides`): *"a joiner that FOLLOWS a virama is orthography, not hiding, and is
kept."* Ours is that rule **plus clauses 3 and 4, which copy #4 does not have** — it never looks
past the joiner, so a trailing joiner, a doubled joiner and a cross-script joiner all keep their
exemption there. Those are two open defects in copy #4.

**WHAT WE DID NOT TAKE FROM COPY #4.** Its other half exempts a joiner **between two
`Extended_Pictographic` characters**, so a family emoji is not shattered into its parts. Not
adopted, for two reasons: Python's `unicodedata` does not expose that property, so adopting it would
mean hand-writing a **fifth** copy of a Unicode table inside the very change whose subject is that
four copies is three too many; and copy #5's argument is sound for emoji — *"a tool ARGUMENT is not
prose; it is the exact value about to be written to a record"* — even though it is not sound for a
conjunct. Not adopting it changes nothing: an emoji joiner was escaped before and is escaped now.

**WHAT THE RANGE COSTS, MEASURED.** Fifty-seven of the 69 viramas now keep no exception at all —
Tibetan, Myanmar, Khmer, Chakma, Javanese, Saurashtra and the rest escape their own conjuncts
exactly as they did before this rule existed. That is an ugly card, never a hidden character: **the
rule fails CLOSED**, and widening it is a decision that has to come with the false-positive
measurement above. Within the twelve that remain, of the 69 viramas **60**
have every letter of their own script inside the virama's own 128-point block. The nine that do not are DEVANAGARI (81 of its 90 letters are inside; the nine outside are
the Devanagari Extended-A candrabindu signs and `DEVANAGARI LETTER AY`), TIBETAN (5 of 50), MYANMAR
(71 of 120, both viramas), TAI THAM, two MEETEI MAYEK, SOYOMBO and GUNJALA GONDI. Of the twelve in range, only DEVANAGARI is imperfect — 81 of its 90 letters are inside its own
block; the nine outside are the Extended-A candrabindu signs and `DEVANAGARI LETTER AY`, which
simply keep no exception.

## 4. TABLE TWO — THE VIRAMAS THE EXCEPTION MAY FIRE ON

Copy #1 **reads the combining class from the library** — `unicodedata.combining(ch) == 9` — and
intersects it with the range of §3; it has no table. Copy #2 carries a table only because JavaScript
regular expressions cannot ask for a combining class; it is generated, and the drift test recomputes
it. **Copies #4 and #5 write out SIXTEEN by hand**, which is both too many (they include Tibetan,
Myanmar and Khmer, whose joiner behaviour they never measured) and too few (they miss U+0D3B and
U+0D3C, two Malayalam viramas). That is table drift caught in the act, and it is why copy #1 has no
table at all.

```viramas
U+094D U+09CD U+0A4D U+0ACD U+0B4D U+0BCD U+0C4D U+0CCD U+0D3B U+0D3C U+0D4D U+0DCA
```

Twelve: Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil, Telugu, Kannada, Malayalam (three of
them) and Sinhala. Unicode gives **69** code points combining class 9 in all; §3 says why the other
57 are excluded.

## 5. TABLE THREE — THE VECTORS EVERY COPY MUST AGREE ON

Input on the left, the displayed form on the right, both as Python `repr` of the escaper's output
(`_escaped` / `escapeForDisplay`). The drift test runs every line against copy #1; the JS suite's
`joinerInsideAWord.spec.js` runs the same list against copy #2. **A copy that disagrees with one
line of this table is wrong, whichever copy it is.**

```vectors
'\u0dc1\u0dca\u200d\u0dbb\u0dd3'	'\u0dc1\u0dca\u200d\u0dbb\u0dd3'	Sinhala conjunct — kept
'\u0b95\u0bcd\u200d\u0bb7'	'\u0b95\u0bcd\u200d\u0bb7'	Tamil conjunct — kept
'\u0915\u094d\u200d\u0937'	'\u0915\u094d\u200d\u0937'	Devanagari conjunct — kept
'\u0dc1\u0dca\u200c\u0dbb'	'\u0dc1\u0dca\u200c\u0dbb'	ZWNJ asks for the separate form — kept
'\u0dc1\u0dca\u200d'	'\u0dc1\u0dca\\u200d'	clause 1 — nothing after it
'\u200d\u0dbb'	'\\u200d\u0dbb'	clause 1 — nothing before it
'\u0dc1\u0dca\u200d \u0dbb'	'\u0dc1\u0dca\\u200d \u0dbb'	clause 3 — a space is not a letter
'\u0dc1\u0dca\u200d.\u0dbb'	'\u0dc1\u0dca\\u200d.\u0dbb'	clause 3 — punctuation
'\u0dc1\u0dca\u200d\u0dcf'	'\u0dc1\u0dca\\u200d\u0dcf'	clause 3 — a vowel sign of the SAME block
'\u0dc1\u0dca\u200d\u0dca'	'\u0dc1\u0dca\\u200d\u0dca'	clause 3 — a second virama
'\u0dc1\u0dca\u200d\u0de6'	'\u0dc1\u0dca\\u200d\u0de6'	clause 3 — a digit of the same script
'\u0dc1\u0dca\u200d\u200d\u0dbb'	'\u0dc1\u0dca\\u200d\\u200d\u0dbb'	doubled — both halves marked
'\u0dc1\u200d\u0dbb'	'\u0dc1\\u200d\u0dbb'	clause 2 — no virama, however Indic the letters
'SO-000A\u094d\u200dx'	'SO-000A\u094d\\u200dx'	clause 4 — a Devanagari virama cannot license a Latin x
'\u0dc1\u0dca\u200d\u0937'	'\u0dc1\u0dca\\u200d\u0937'	clause 4 — Sinhala virama, Devanagari letter
'paid\u200dunpaid'	'paid\\u200dunpaid'	the original attack, untouched by the exception
'gnp\u202eexe'	'gnp\\u202eexe'	a bidi override is not a joiner and takes no exemption
'\u202e\u0dc1\u0dca\u200d\u0dbb'	'\\u202e\u0dc1\u0dca\u200d\u0dbb'	the joiner kept, the override STILL marked
'\u0dc1\u0dca\u202e\u0dbb'	'\u0dc1\u0dca\\u202e\u0dbb'	a virama licenses a joiner and nothing else
'SO-0001\u3164'	'SO-0001\\u3164'	the invisible LETTER run 15 closed
'\u0d15\u0d3c\u200d\u0d37'	'\u0d15\u0d3c\u200d\u0d37'	Malayalam U+0D3C, a virama the front ends' sixteen omit — kept
'\u0e01\u0e3a\u0e02'	'\u0e01\u0e3a\u0e02'	Thai has a combining-class-9 mark and no joiner: the plain word
'\u0e01\u0e3a\u200d\u0e02'	'\u0e01\u0e3a\\u200d\u0e02'	clause 2 range — Thai takes no joiner, so this one only hides
'\u0eba\u200d\u0e81'	'\u0eba\\u200d\u0e81'	clause 2 range — Lao U+0EBA
'\u2d31\u2d7f\u200d\u2d30'	'\u2d31\u2d7f\\u200d\u2d30'	clause 2 range — Tifinagh U+2D7F is itself the consonant joiner
'\u1000\u103a\u200d\u1001'	'\u1000\u103a\\u200d\u1001'	clause 2 range — Myanmar ASAT kills, it does not stack
'\U00011005\U0001107f\u200d\U00011006'	'\U00011005\U0001107f\\u200d\U00011006'	clause 2 range — Brahmi NUMBER JOINER
'\u0f40\u0f84\u200d\u0f41'	'\u0f40\u0f84\\u200d\u0f41'	clause 2 range — Tibetan is out of range and keeps no exception
'Sales Order SO-0001'	'Sales Order SO-0001'	the control — a rule that escaped everything would pass the rest
```

## 6. WHAT IS *NOT* DEFENDED, SAID OUT LOUD

- **THE DECLARED COST OF THE EXCEPTION ITSELF.** `ශ්ර` and `ශ්‍ර` differ only by a conjunct joiner,
  and what tells them apart on screen is that a conformant Sinhala renderer draws the second as a
  touching conjunct. **In a font that does not form that conjunct, the two are one set of pixels.**
  This is inherent to any joiner exception — copy #4 accepted it too, and calls it "a documented
  trade" — and it is the price of not destroying the word. It is bounded by §3's four clauses to
  exactly the case where the joiner is asking a renderer for something. `TestTwoValuesAReaderCannot
  TellApartStillEscapeDifferently.CONJUNCT_PAIRS` names every pair that pays it, one by one, so the
  cost is bounded only by what a font actually forms, which is not a thing a test can see:
  `CONJUNCT_PAIRS` holds EXAMPLES, not a census. An earlier version of this paragraph claimed the
  list was complete and that nothing could join it unnoticed; a reviewer found two pairs inside the
  range already paying the cost and in neither list — the Sinhala ZWNJ case (which is §5's own
  "kept" vector, and inert in every conformant font, not merely in a font lacking a conjunct) and
  Tamil k+p, which forms no ligature anywhere. Both are now in the list, and the assertion on its
  length is gone, because a count nothing enforces reads as a bound.
- **THE TWO COPIES CAN DISAGREE ACROSS A UNICODE VERSION.** Clause 3 asks Python
  `unicodedata.category(ch)[0] == "L"` and JavaScript `\p{L}`, and the two runtimes ship different
  UCD versions (bench Python 3.14.7 is UCD 16.0.0; Node v24.21.0 is Unicode 17.0). **Measured
  29 Sep 2026 against the code in this commit**, by running both shipped copies over every (virama,
  joiner, same-block neighbour) triple: **4 inputs get opposite joiner decisions** — two code
  points, `U+0C5C` (Telugu) and `U+0CDC` (Kannada), both added in Unicode 17, once per joiner. The
  smallest is `U+0041 U+0C4D U+200D U+0C5C U+005A`, where the engine escapes the joiner and the
  panel does not: the PANEL is the permissive side, because it is the newer. Not closed here —
  closing it means generating the letter table for U+0900–U+0DFF into the panel (89 ranges), a
  fifth table that wants its own decision. Pinned on the Python side by
  `test_the_divergence_between_the_two_copies_is_exactly_two_code_points` and on the panel's side by
  `joinerInsideAWord.spec.js`.

  **THIS NUMBER WAS WRONG ONCE AND THE WAY IT WAS WRONG IS WORTH KEEPING.** It said 98, which was
  measured against the previous commit, when 69 viramas were live rather than 12. The narrowing cut
  it 24-fold and the figure was carried over unchanged — dated, and presented as measured against
  the code beside it. A measurement carries its date AND the code it was taken against, or it does
  not go in. `test_the_note_states_the_divergence_at_its_current_size` now fails if this paragraph
  and the measurement part company.

- **Homoglyphs.** `Раураl` in Cyrillic draws identically to the Latin word and produces no escape
  and no quote, because every code point in it is an ordinary visible letter. A mixed-script or
  Unicode-skeleton check is a different mechanism with its own false positives and nobody has
  decided it.
- **A long run of combining marks.** `Delete` + forty U+0301 overruns the lines above and below it.
  The marks are legitimate orthography everywhere else, so the mitigation is a cap on consecutive
  `\p{Mn}`, not an escape.
- **`_confirmation_question`'s untemplated fallback body**, which is `json.dumps(..., indent=2)`
  and never passes through the escaper at all. `ensure_ascii=True` means EVERY non-ASCII character
  is escaped there, so a Sinhala value on a card with no sentence is still unreadable — a bigger
  defect than the joiner and a different one. It is a CLAUDE.md rule-4 function; it needs its own
  spec. Pinned by `TestTheFallbackDumpIsADifferentDefectEntirely` in
  `flow/tests/test_s23_a_joiner_inside_a_word.py`.

## 7. WHAT `q_flow_tools` MUST ADOPT

One paragraph, for the lane that owns that tree. `q_flow_tools` carries copy #3: the identical 17
ranges of §2, ported from `flow/lib/agent.py`, with no joiner exception — so it escapes ZWJ and
mangles Sinhala exactly as this repository did before 29 September 2026. It needs §3 added to its
escaper, whole and with all four clauses: the viramas read from `unicodedata.combining(ch) == 9`
rather than typed out, the letter-after and same-block clauses included rather than only the
virama-before clause the web apps have, and the vectors of §5 added as tests. Nothing else changes —
§1 and §2 are already correct there. It must not adopt the emoji half of copy #4's rule, for the
reason in §3.
