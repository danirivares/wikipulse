// Wikipedia-focused semantic hazard taxonomy (Gemma 4 E4B QAT) + structural heuristics.
export const HAZARD_CATALOG = [
  {
    code: "vandalism",
    label: "Vandalism & Hoaxes",
    scope:
      "Deliberate defacement, gibberish, hoaxes (such as fake deaths), graffiti, or prank edits.",
  },
  {
    code: "spam",
    label: "Spam & Scams",
    scope:
      "Commercial ads, SEO link injection, phishing URLs, financial scams, or self-promotion.",
  },
  {
    code: "hate_speech",
    label: "Hate Speech",
    scope:
      "Slurs, dehumanization, or incitement to hatred against protected groups.",
  },
  {
    code: "harassment",
    label: "Harassment & Attacks",
    scope:
      "Targeted personal attacks, threats, bullying, or malicious defamation against individuals.",
  },
  {
    code: "doxxing",
    label: "Private Info",
    scope:
      "Exposing private personal details such as home addresses, phone numbers, IDs, or credentials.",
  },
  {
    code: "sexual_explicit",
    label: "Sexual Content",
    scope:
      "Explicit pornography, graphic sexual vandalism, or child exploitation — never clinical or anatomical material.",
  },
  {
    code: "violence_harm",
    label: "Violence & Self-Harm",
    scope:
      "Violent threats, incitement, self-harm encouragement, or actionable weapon and crime instructions.",
  },
];

export const HEURISTIC_CATALOG = [
  {
    code: "heur:blanking",
    label: "Page Blanking",
    scope: "Removes at least 70% of an article that is 500 bytes or larger.",
  },
  {
    code: "heur:mass_delete",
    label: "Mass Deletion",
    scope: "Net removal of 2,000 bytes or more in a single edit.",
  },
  {
    code: "heur:no_comment",
    label: "No Edit Summary",
    scope: "Edit submitted without an edit summary in the revision log.",
  },
];

// Full label lookup: active semantic codes, heuristics, and legacy S1-S14 fallback labels.
export const HAZARD_LABELS = {
  ...Object.fromEntries(HAZARD_CATALOG.map((h) => [h.code, h.label])),
  ...Object.fromEntries(HEURISTIC_CATALOG.map((h) => [h.code, h.label])),
  S1: "Violent Crimes",
  S2: "Non-Violent Crimes",
  S3: "Sex-Related Crimes",
  S4: "Child Exploitation",
  S7: "Privacy",
  S9: "Indiscriminate Weapons",
  S10: "Hate",
  S11: "Self-Harm",
  S12: "Sexual Content",
  S14: "Malicious Code",
};

export function hazardLabel(code) {
  return HAZARD_LABELS[code] || code;
}
