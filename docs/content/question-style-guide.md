# Oltivra question style guide

This guide is for every question-bank batch. It was written after the 2026-09-27 geography pilot was rejected
for being templated and repetitive ("capital of X", "flag of X", "which river flows through X").

A player has **15 seconds** on a phone. A good question is **quick to read** and **interesting in itself**. It is
**fair**: you can answer it by knowing or by thinking. It **teaches something**: a player who gets it wrong still
thinks "huh, I didn't know that".

## 1. What makes a question good

1. **A hook.** Every question carries a surprising, vivid or human detail: a record, a paradox, a name's
   origin, an odd fact, a number that sticks. "What is the capital of Kenya?" has no hook.
2. **Solvable by reasoning.** Put a clue in the wording (etymology, a comparison, a scenario) so a thinking player
   can get there without having memorised the fact. This is what separates trivia from a quiz on rote facts.
3. **One clear, uncontested answer.** Avoid facts that change with sources or time: current populations,
   "largest city" rankings, disputed borders, disputed records.
4. **Short.** Aim for 110 characters or fewer and never more than 160. One sentence and one idea. Options should
   be 32 characters or fewer.
5. **Four plausible options of the same kind.** Distractors should be the *misconceptions* people actually hold
   (Sydney for Australia's capital, Sahara for "largest desert"). No joke options, no "all of the above". If an
   option is obviously wrong, the question is really three options.
6. **Translatable.** Each question must work in Turkish as well. Avoid English wordplay, English-only spelling
   quirks and US-only pop knowledge.
7. **Respectful and safe.** No politics, religion, tragedies used as trivia, or national stereotypes.

## 2. Archetypes (mix them)

| # | Archetype | Pattern | Example hook |
|---|---|---|---|
| A | Name origin | "X's name comes from the word for…" | Argentina ← *argentum* (silver) |
| B | Surprise / myth-buster | the intuitive answer is wrong | Sudan has more pyramids than Egypt |
| C | Comparison | "Which of these is furthest north / biggest / oldest?" | Reykjavík vs Oslo vs Helsinki |
| D | Scenario | "If you went due south from X, you'd reach…" | Detroit → Canada |
| E | Common thread | "What do A, B, C and D have in common?" | Bolivia, Nepal… landlocked |
| F | Number sense | "Roughly how many / what share…?" | Baikal holds about ⅕ of fresh surface water |
| G | Record with a story | a superlative plus a reason why it's remarkable | France has the most time zones |
| H | Odd one out | "Which of these is NOT…?" (use sparingly) | the Equator misses Nigeria |
| I | Cross-over | geography meets food, language, history, sport or science | Brazil speaks Portuguese |
| J | Plain recall | a classic fact asked directly | only when the fact itself is remarkable |

## 3. Quotas per category bank

- No single template above **3%** of a category. For example, at most 30 of 1,000 geography questions are plain
  "capital of X".
- Plain recall (archetype J) is at most **20%** of a category.
- No archetype is above **25%**.
- Within each block of 100 questions:
  - no two questions share the same correct answer;
  - every subcategory is represented;
  - answers come from every inhabited continent.
- Difficulty is 40% EASY, 40% MEDIUM and 20% HARD. **Difficulty means how many players can know *or reason* it,
  not how obscure it is.** A HARD question must still be fair and interesting. It must never be "name this
  random small town".

## 4. Writing checklist (per question)

- [ ] Does it have a hook? Would a player tell a friend about the answer?
- [ ] Can a thinking player narrow it down?
- [ ] Is the answer uncontested on English Wikipedia (the source)?
- [ ] Are all four options plausible, of the same type and similar in length?
- [ ] Is it 110 characters or fewer, and readable in about 5 seconds?
- [ ] Does it work in Turkish?
- [ ] Is it a template that has already hit its quota?

## 5. Process

1. For each category, list 150–200 candidate *facts with hooks* first, without writing questions. Drop the dull
   ones.
2. Write the questions in batches of 100 and check them with `python -m tools.content.draft check <category>`.
   That command covers competitive text rules, duplicates and the difficulty mix.
3. Review the archetype and subcategory counts for each batch against the quotas above.
4. When the category's English is complete, translate the whole category into Turkish. The translation is idiomatic,
   not word for word, and uses the standard Turkish forms of place names. Then merge, build and import.
