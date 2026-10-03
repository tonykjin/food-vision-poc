# fatsecret Vendor Questions (DRAFT, not sent)

**Status:** draft prepared 2026-10-02 (Prompt 07). **Not sent.** Nothing in this file means a permission is approved. Record answers in `docs/provider-readiness.md` with the date, the sender and the exact wording (Prompt 08).

Send through https://platform.fatsecret.com/contact or your account contact. Fill in the bracketed fields first. Don't include API keys or credentials.

---

**Subject:** Image Recognition add-on: access, data-use and retention questions for a pilot evaluation

Hello fatsecret Platform team,

We're [COMPANY], building a food-photo nutrition feature. We'd like to evaluate the Image Recognition API v2 (`/rest/image-recognition/v2`) in a small private pilot. We'd compare its results against independently weighed reference meals, and against a second internal pipeline built on USDA FoodData Central data. Our developer account is [ACCOUNT EMAIL / APP NAME]. Before we start, please confirm the following.

**Access and edition**
1. Which editions can have the Image Recognition add-on? Is it available on Basic or Premier Free for US data, or only with Premier? We qualify as [STARTUP / OTHER].
2. What does the add-on cost for a [US-only / list markets] pilot of about [N] image requests over [PERIOD]? Is there a trial or evaluation allowance?
3. Are there rate limits or monthly request caps on the image endpoint for our edition?

**Localization**
4. Without Premier, are image results limited to US foods, with `region` and `language` ignored? Which markets would we need to add later for [TARGET COUNTRIES]?

**Authentication and network**
5. How many IP addresses or CIDR ranges can we register for token requests on our edition? Is there guidance for cloud CI runners and hosts whose egress IPs change?
6. Are there limits on token reuse or concurrent tokens beyond `expires_in` (86400 s)?

**Attribution**
7. What exact attribution do you require in a private, internal pilot UI that only our team and invited testers see? Is a "Powered by fatsecret" link enough, and where must it appear?

**Retained results**
8. Your Terms §1.5 require non-storable content to be removed within 24 hours, and the image docs say only `food_id` and `serving_id` are storable. To compare results within a benchmark run, can we keep a response (food names, portions, nutrients) in memory or temporary storage for the length of an evaluation run that may last longer than 24 hours? If not, what's the maximum?
9. Can we store `food_id` and `serving_id` with our own sample IDs and timestamps, and later re-fetch nutrition through `food.get` for re-scoring?

**Derived evaluation metrics**
10. Can we keep **derived metrics** indefinitely? These are numbers we compute ourselves, such as absolute calorie error versus our reference, latency, success or failure, and aggregate accuracy statistics. They contain no fatsecret food names or nutrient values.
11. Can we share aggregate comparisons, such as "Provider A median calorie error X kcal on N meals", internally with cofounders and investors? Can we share them externally, and if so on what conditions?

**Exports and caching**
12. Can internal reports or CSV exports include per-sample fatsecret results (names, portions, nutrients) for team review? If yes, under what retention limit and access restrictions?
13. Does "caching", which the Premier tiers list as a feature, allow us to persist responses beyond 24 hours? What are its terms?

**Future training use**
14. Can we use fatsecret responses, or labels derived from them, to train, fine-tune or evaluate our own machine-learning models? If not, can we use them for evaluation only?
15. Are the photos we submit kept or used by fatsecret, for example to improve your models? Can we opt out, and what is your retention period for submitted images?

**Other**
16. Is there an acceptable-use limit on submitting photos of packaged products or menu items (where the label is visible but not only a nutrition panel), given that label-only images return error 211?

We'd appreciate written confirmation for each point so we can configure our storage policy correctly. Thank you.

[NAME]
[TITLE], [COMPANY]
[CONTACT]

---

## Internal checklist (not for sending)

- [ ] Fill in the bracketed fields; owner = Tony Jin (vendor/access/spend)
- [ ] Sent on: PENDING, by: PENDING
- [ ] Answers recorded in `docs/provider-readiness.md`, with `PROVIDER_OUTPUT_POLICY_VERSION` bumped only once written answers are in
- [ ] Until then: `PERSIST_PROVIDER_OUTPUTS=false`; App A results stay in memory for the length of a run only
