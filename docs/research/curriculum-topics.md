# The podstawa programowa as Curriculum topics

Research for [#9](https://github.com/KeeNeePL/Classlop/issues/9). Checked 2026-10-08 against the Sejm ELI API, the Dziennik Ustaw PDFs, ZPE and cke.gov.pl.

## Answer

- **Three mathematics podstawy are in force in 2026/27**, depending on the grade. Classlop needs all three as Curriculum topic sets, each tagged with the act it comes from.
- **There is no official machine-readable list.** The authoritative text is the Dziennik Ustaw act, served free by the Sejm ELI API as PDF and, for some acts, as semi-structured HTML. Build the list once, check it by hand, and commit it to the repo as data (about 400 requirements in all).
- **Identifiers:** the act's own numbering ("dział" + "punkt" within a grade band, and P/R level in liceum) is stable for the life of the act. CKE already cites liceum requirements as `I.8)` and `II.R5)`; reuse that form.
- **Licence:** the podstawa is a normative act and is not subject to copyright (art. 4 pkt 1 of the copyright act). Commit its full text freely. CKE papers are very likely "urzędowe materiały" (art. 4 pkt 2), but CKE publishes no licence and marks its papers "Układ graficzny © CKE 2022". Use them in the teacher's private Knowledge base. In this public repo, keep only links and metadata (paper code, task number, requirement IDs).

## Which podstawa applies in 2026/27

| Grades | Act (mathematics part) | Text formats | Status |
|---|---|---|---|
| SP I and IV (then rising one grade a year) | Rozporządzenie MEN z 11 marca 2026, [Dz.U. 2026 poz. 378](https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20260000378), zał. nr 2, section MATEMATYKA. Amended by [Dz.U. 2026 poz. 958](https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20260000958) (no mathematics changes) | PDF only (`textHTML: false`) | In force from 2026-09-01 |
| SP II, III and V-VIII | Old podstawa: Rozporządzenie MEN z 14 lutego 2017, [Dz.U. 2017 poz. 356](https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20170000356), zał. nr 2, in the wording of [Dz.U. 2024 poz. 996](https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20240000996) | PDF and structured HTML (of 2024/996) | Still applied under § 4 ust. 2 of 2026/378, although ISAP marks 2017/356 as repealed |
| Liceum and technikum, all classes | Rozporządzenie MEN z 30 stycznia 2018, [Dz.U. 2018 poz. 467](https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20180000467), zał. nr 1, in the wording of [Dz.U. 2024 poz. 1019](https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20240001019) | PDF only for the current wording | In force since 2024/25 |

Supporting facts:

- 2026/378 § 4 ust. 1: the new podstawa applies "od roku szkolnego 2026/2027 w klasach I i IV szkoły podstawowej, a w latach następnych również w kolejnych klasach". § 4 ust. 2 keeps the old podstawa for grades II, III and V-VIII in 2026/27, for III and VI-VIII in 2027/28, and for VII-VIII in 2028/29 ([Dz.U. 2026 poz. 378, PDF](https://api.sejm.gov.pl/eli/acts/DU/2026/378/text.pdf)). The July amendment 2026/958 rewrites § 4 ust. 1 and the shared clause of ust. 2. It only touches other subjects (kształcenie obronne, edukacja zdrowotna) and changes nothing for mathematics ([Dz.U. 2026 poz. 958, PDF](https://api.sejm.gov.pl/eli/acts/DU/2026/958/text.pdf)).
- 2024/996 § 1 pkt 1 replaces zał. nr 2 of 2017/356 in full, so its annex is the complete old SP text. The 2025 amendments ([2025/378](https://api.sejm.gov.pl/eli/acts/DU/2025/378), [2025/1052](https://api.sejm.gov.pl/eli/acts/DU/2025/1052)) do not change mathematics. 2025/1052 only cross-references "Matematyka: Dział II" from wychowanie fizyczne.
- 2024/1019 § 1 pkt 2 replaces zał. nr 1 of 2018/467 in full. § 2 applies it from 2024/25 to all liceum and technikum students. Later amendments ([2025/382](https://api.sejm.gov.pl/eli/acts/DU/2025/382), [2025/1035](https://api.sejm.gov.pl/eli/acts/DU/2025/1035), [2026/947](https://api.sejm.gov.pl/eli/acts/DU/2026/947)) contain no mathematics changes.
- The new SP general-education act for branżowa szkoła I stopnia is separate ([Dz.U. 2026 poz. 1012](https://api.sejm.gov.pl/eli/acts/DU/2026/1012)). It is out of scope unless the teacher teaches there.
- A new liceum/technikum podstawa is expected from 2027/28 under Reforma26. MEN has recruited experts for it ([gov.pl](https://www.gov.pl/web/edukacja/nabor-ekspertow-do-prac-nad-podstawami-programowymi-dla-szkol-ponadpodstawowych)), but I found no published draft or act. Not verified on RCL.
- Grades I-III teach mathematics inside integrated "edukacja wczesnoszkolna", not as a separate subject. Probably out of scope for a mathematics teacher.

## Where to get the text, and how machine-readable it is

| Source | What it gives | Usefulness |
|---|---|---|
| Sejm ELI API, `https://api.sejm.gov.pl/eli/acts/DU/{year}/{pos}` | JSON metadata: title, status, `inForce`, entry into force, amending and amended acts, available formats. `/text.pdf` always; `/text.html` when `textHTML` is true | Best authoritative source, no key needed. Use the metadata to detect future amendments |
| ELI HTML of 2024/996 | Old SP podstawa with markup: each dział is `div.unit_none` with `id="none_I"`, each point `div.unit_pint` with `id="none_I-pint_1"` and a unique `data-bookmark` such as `_002_z1_448_1`. Formulas use `<SUP>` and `<I>` | Easiest to parse. The ids repeat across grade bands and subjects, so derive your own ID from band + dział + punkt. Has small OCR-style errors ("interpretuj e") |
| ELI HTML of 2018/467 | The **original 2018** liceum text | Do not use: outdated. The current wording is in the 2024/1019 annex, and that act's HTML omits its zał. nr 1 |
| ELI PDF of 2026/378 and 2024/1019 | Current text of the new SP and liceum podstawy | `pdftotext -layout` gives clean numbered lines. Formulas set in a maths font come out garbled (for example the Newton symbols in liceum II.R4 and the rational expressions in II.R6 and III.1), so those lines need manual correction |
| [ZPE podstawa browser](https://zpe.gov.pl/podstawa-programowa) (MEN) | HTML tree of the podstawa with hierarchical `data-node-id` / `data-id` paths (`4157.4158.21640.4160`), `cc2_number` and `cc2_description` per point | Clean and scrapeable, but labelled "rok szkolny 2025/2026": it has the 2024 liceum and old SP text, not the 2026 SP podstawa yet. Node ids are internal to ZPE, not legal identifiers |
| [CKE podstawa page](https://cke.gov.pl/egzamin-maturalny/egzamin-maturalny-w-formule-2023/podstawa-programowa/) | PDF of the 2024 liceum podstawa (`DU_programowej_2024.pdf`) | Same text as the act. CKE marking schemes map every task to requirement IDs |
| IBE / ORE commentaries ([IBE komentarz](https://ibe.edu.pl/files/Reforma26/Komentarze_dydaktyczne/Matematyka_komentarz_do_podstawy.pdf)) | Didactic commentary on the 2026 SP podstawa | Not the requirements themselves. The ORE guide is CC BY-NC 4.0 per its imprint (secondary, not checked) |

## Identifier scheme

How each act numbers its requirements (verified in the PDFs and HTML above):

- **New SP (2026/378):** two grade bands, "Klasy IV-VI" and "Klasy VII i VIII", each restarting the numbering. Działy carry Arabic numerals (`1. Liczby. Uczeń:`), points `1)`, sub-points `a)`. IV-VI: 1 Liczby, 2 Miary, 3 Algebra, 4 Figury, 5 Dane, 6 Myślenie matematyczne. VII-VIII: 1 Liczby, 2 Algebra, 3 Figury, 4 Dane i zdarzenia losowe, 5 Myślenie matematyczne. Some points end with "– moduł ekonomiczno-finansowy" (a flag, not a separate list). After the requirements comes a separate numbered list of "doświadczenia edukacyjne", which are not requirements. About 86 points in IV-VI and 46 in VII-VIII.
- **Old SP (2017/356 as of 2024/996):** two bands, "KLASY IV-VI" (działy I-XIV) and "KLASY VII i VIII" (działy I-XV), Roman numerals that restart in each band, points `1)`. About 160 points.
- **Liceum (2018/467 as of 2024/1019):** działy I-XIII. Each has "Zakres podstawowy. Uczeń:" with points `1)`, then "Zakres rozszerzony. Uczeń spełnia wymagania określone dla zakresu podstawowego, a ponadto:" with its own `1)` numbering. Some blocks are a single unnumbered sentence (I rozszerzony: "stosuje wzór na zamianę podstawy logarytmu"; XIII podstawowy). About 114 numbered points.
- **CKE notation** (marking scheme for matura 2026, [MMAP-R0-100-2605-zasady.pdf](https://cke.gov.pl/images/_EGZAMIN_MATURALNY_OD_2023/Arkusze_egzaminacyjne/2026/Matematyka/poziom_rozszerzony/MMAP-R0-100-2605-zasady.pdf)): podstawowy `I.8)`, `VIII.11)`; rozszerzony `II.R5)`, `XIII.R4)`. Each task also lists its "wymaganie ogólne" (I-IV).

Suggested Curriculum topic ID: `{set}:{band}:{code}`, where the code copies the act's numbering.

| Set | Example IDs |
|---|---|
| `sp2026` | `sp2026:4-6:1.17`, `sp2026:4-6:1.28b`, `sp2026:7-8:5.3a` |
| `sp2017` | `sp2017:4-6:II.6`, `sp2017:7-8:I.5` |
| `lo2024` | `lo2024:I.8`, `lo2024:II.R5`, unnumbered blocks as `lo2024:XIII` and `lo2024:I.R` |

Fields worth keeping per Curriculum topic: id, set (with the act's ELI, e.g. `DU/2026/378`), band or level (P/R), dział number and name, point, sub-point, verbatim text, and the moduł ekonomiczno-finansowy flag. The `lo2024` codes match CKE's codes once the `)` is dropped, so CKE tasks can be tagged without translation.

Stability: the numbering is stable while an act's wording stands. But amendments in this area replace whole annexes and renumber them: 2024/996 and 2024/1019 both did. So the set prefix (tied to the act version) is part of the identity. When 2027 brings a new liceum podstawa, it becomes a new set, not an edit.

## Licences

**Podstawa programowa: free to copy, commit and embed.** Art. 4 of the copyright act ([tekst jednolity Dz.U. 2025 poz. 24](https://api.sejm.gov.pl/eli/acts/DU/2025/24/text.pdf)): "Nie stanowią przedmiotu prawa autorskiego: 1) akty normatywne lub ich urzędowe projekty; 2) urzędowe dokumenty, materiały, znaki i symbole; [...]". The podstawa is an annex to a rozporządzenie, so it falls under pkt 1. Committing the full requirement text to this public repo is fine.

**CKE exam papers (arkusze, zasady oceniania, informatory): probably free, but not licensed.**

- CKE is a state body, and published exam papers are the textbook candidate for "urzędowe materiały" under art. 4 pkt 2.
- CKE publishes no licence or terms of use. None appear on cke.gov.pl or the arkusze pages.
- The 2026 matura mathematics paper carries "Układ graficzny © CKE 2022" on its cover ([MMAP-P0-100-A-2605-arkusz.pdf](https://cke.gov.pl/images/_EGZAMIN_MATURALNY_OD_2023/Arkusze_egzaminacyjne/2026/Matematyka/poziom_podstawowy/MMAP-P0-100-A-2605-arkusz.pdf)), so CKE does assert rights at least in the layout.
- Case law on what counts as "urzędowy materiał" is split. SN IV CKN 458/00 reads it broadly but adds that art. 4 is not a licence to reproduce freely. SN V CSK 337/08 reads it narrowly. I know of both only through secondary summaries and could not open them on sn.pl. I found no ruling on CKE papers specifically.
- Mathematics papers rarely embed third-party texts or images, but any that do are not CKE's to free.

Practical rule:

- Use CKE papers in the teacher's private Knowledge base (download, extract tasks, embed).
- In the public repo and in issues, keep links plus metadata only: paper code such as `MMAP-P0-100-2605`, task number, points and requirement IDs. Do not commit copies, transcriptions or page images.
- This qualifies the line in #1 that calls CKE papers "freely licensed material". They are most likely unprotected, not licensed.

## Not verified

- Whether a draft of the 2027 liceum podstawa exists on RCL.
- The full texts of SN IV CKN 458/00 and V CSK 337/08 (cited from secondary sources).
- Point counts are from a grep over `pdftotext` output and are approximate.
- Whether ZPE will publish a 2026/27 edition of its podstawa browser, including the 2026 SP text.

## Sources

- Sejm ELI API metadata and texts: [2026/378](https://api.sejm.gov.pl/eli/acts/DU/2026/378), [2026/958](https://api.sejm.gov.pl/eli/acts/DU/2026/958), [2017/356](https://api.sejm.gov.pl/eli/acts/DU/2017/356), [2024/996](https://api.sejm.gov.pl/eli/acts/DU/2024/996), [2018/467](https://api.sejm.gov.pl/eli/acts/DU/2018/467), [2024/1019](https://api.sejm.gov.pl/eli/acts/DU/2024/1019), [2026/947](https://api.sejm.gov.pl/eli/acts/DU/2026/947), [2026/1012](https://api.sejm.gov.pl/eli/acts/DU/2026/1012), [copyright act 2025/24](https://api.sejm.gov.pl/eli/acts/DU/2025/24)
- ISAP pages: [WDU20260000378](https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20260000378), [WDU20240000996](https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20240000996), [WDU20240001019](https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20240001019)
- MEN: [gov.pl announcement of the signed 2026 SP podstawa](https://www.gov.pl/web/edukacja/nowe-podstawy-programowe-wychowania-przedszkolnego-i-ksztalcenia-ogolnego-dla-szkoly-podstawowej-wraz-ze-zmianami-w-ramowych-planach-nauczania-dla-publicznych-szkol-podstawowych--rozporzadzenia-podpisane), [ZPE: SP mathematics](https://zpe.gov.pl/podstawa-programowa/szkola-podstawowa/matematyka), [ZPE: liceum mathematics](https://zpe.gov.pl/podstawa-programowa/szkola-ponadpodstawowa/matematyka)
- CKE: [matura 2023 formula, arkusze 2026](https://cke.gov.pl/egzamin-maturalny/egzamin-maturalny-w-formule-2023/arkusze/2026-2/), [podstawa programowa page](https://cke.gov.pl/egzamin-maturalny/egzamin-maturalny-w-formule-2023/podstawa-programowa/), [marking scheme, basic 2026](https://cke.gov.pl/images/_EGZAMIN_MATURALNY_OD_2023/Arkusze_egzaminacyjne/2026/Matematyka/poziom_podstawowy/MMAP-P0-100-2605-zasady.pdf)
