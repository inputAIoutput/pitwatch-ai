# 0001. Hybrid Predictive Pipeline (Calculated Physics & LLM Synthesis)

We decided to calculate deterministic race telemetry (pit-loss threat windows, tyre degradation rates, and lap delta vs. track temperature) in Python before passing this enriched tactical context to the AI Provider (OpenRouter/SLMs). This avoids LLM hallucinations on basic mathematics while leveraging language model reasoning for un-modeled tactical bluffs, radio deciphering, and multi-lap scenarios.
