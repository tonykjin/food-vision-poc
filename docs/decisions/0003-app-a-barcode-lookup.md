# 0003 — App A reads product barcodes locally and looks them up with fatsecret

**Status:** Proposed
**Date:** 2026-10-13
**Deciders:** PENDING (Tony Jin to accept with the #50 PR)

## Context

A barcode-only photo in App A fails with `empty_recognition`: fatsecret image recognition returns 211 ("No food item detected") because a barcode isn't visible food. Plan §8 A5 deferred barcodes until meal-photo analysis worked (it has since 2026-10-07) and requires barcodes to stay a separate input category, with no model fallback in App A. Issue [#50](https://github.com/tonykjin/food-vision-poc/issues/50).

## Decision

- **New dependency `zxing-cpp==3.1.1`** (Apache-2.0, released 2026-07-29; wheels for Windows and manylinux, so no system library in the Docker image). It decodes UPC-A, UPC-E, EAN-13 and EAN-8 locally, with no external call. Every code's GS1 check digit is verified and the code is normalized to GTIN-13 (UPC-E expanded first), as the fatsecret docs require.
- **New pipeline id `A_barcode`** using fatsecret `food.find_id_for_barcode.v2` (`GET /rest/food/barcode/find-by-id/v2`, OAuth scope `barcode`, Premier Exclusive). The client keeps **one token per scope**, so a key without `barcode` can never break image recognition.
- **Routing only in the App A API** (`ProviderRoutedPipeline`, `ENABLE_BARCODE_LOOKUP`, default true). Exactly one barcode goes to `A_barcode`. Several different barcodes give a typed failure. No barcode runs `A_native` unchanged. The benchmark calls the pipeline without barcodes, so **`A_native` results stay pure**.
- **Honest basis.** The result is one serving as labeled for the product: `nutrition_basis=per_label_serving`, `portion_method=label_serving`, never scaled and never presented as the amount eaten. A serving without grams (ml) stays unresolved, with no density assumption. Confidence rules v3 rate a labeled serving's portion **Low**.
- Same storage policy as `A_native`: restricted fatsecret content stays transient; only `food_id`/`serving_id` are storable.

## Consequences

- Additive contract change (schema 1.0): new enum values `per_label_serving` and `label_serving`. `confidence-rules-v3` replaces v2, so specs frozen under v2 no longer match. Only synthetic specs existed.
- App A can now answer packaged products without guessing portions. Benchmark reporting of a barcode category is still to do; `A_barcode` maps to the fatsecret data source for rights handling.
- A barcode that's blurry, small or partly out of frame isn't read, and the photo goes to image recognition as before.
- Live-verified 2026-10-13: the `barcode` scope is granted on our key, a known product returned a complete labeled serving, and an unknown code returned the typed `no_match`.
