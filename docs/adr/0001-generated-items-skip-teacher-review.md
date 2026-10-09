# Generated and uploaded items enter the item bank without teacher review

AI-generated items go straight into the item bank, with no draft or unreviewed state. We considered making the teacher accept each item first, since a wrong item spoils every submission graded against it, but chose human-over-the-loop instead. Jev re-tags every generated item and it is regenerated when its curriculum topic or difficulty misses the generation request. Items that keep failing that check, or have no matching exemplar, are flagged for the teacher. The teacher still sees each item when picking it into an assignment, and can edit or retire any item at any time.

Item uploads follow the same rule: the AI completes whatever answer, model solution, points and rubric the file lacks, Jev tags each item, and it enters the bank unreviewed. Exercises transcribed with low confidence are flagged rather than held back; only near-duplicates wait for the teacher, who decides on them in the upload summary.
