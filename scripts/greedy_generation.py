"""Explicit, runtime-checked decoding for the original-protocol runners.

Transformers 4.51 can replace global-default values in GenerationConfig with
model-specific sampling defaults. Disable that merge AND pass decoding kwargs.
Inspect the config prepared by the actual generate call, before any tokens run.
"""
from copy import deepcopy

GENERATION_VERSION = 2
POLICY = dict(do_sample=False, num_beams=1, num_return_sequences=1,
              max_new_tokens=256, repetition_penalty=1.0, use_cache=True,
              temperature=1.0, top_p=1.0, top_k=50)


def generate_greedy(model, inputs, tokenizer, stopping_criteria):
    from transformers import GenerationConfig
    config = GenerationConfig(**POLICY,
        eos_token_id=model.generation_config.eos_token_id,
        pad_token_id=(tokenizer.pad_token_id if tokenizer.pad_token_id is not None
                      else tokenizer.eos_token_id), bos_token_id=tokenizer.bos_token_id)
    prepare = model._prepare_generation_config
    audit = {}

    def checked(generation_config, use_model_defaults=None, **kwargs):
        effective, model_kwargs = prepare(generation_config, use_model_defaults, **kwargs)
        mode = effective.get_generation_mode().value
        if use_model_defaults is not False or mode != 'greedy_search':
            raise RuntimeError(f'Expected explicit greedy decoding, got {mode}')
        for key, value in POLICY.items():
            if getattr(effective, key) != value:
                raise RuntimeError(f'Generation setting changed: {key}={getattr(effective, key)!r}')
        audit.update(version=GENERATION_VERSION, mode=mode, use_model_defaults=False,
                     config=deepcopy(effective.to_dict()))
        return effective, model_kwargs

    # One generating thread per backend; restore even on CUDA errors/cancellation.
    had_override = '_prepare_generation_config' in vars(model)
    old_override = vars(model).get('_prepare_generation_config')
    model._prepare_generation_config = checked
    try:
        result = model.generate(**inputs, generation_config=config,
            use_model_defaults=False, **POLICY, stopping_criteria=stopping_criteria)
    finally:
        if had_override:
            model._prepare_generation_config = old_override
        else:
            del model._prepare_generation_config
    if not audit:
        raise RuntimeError('generate() bypassed the generation configuration guard')
    return result, audit
