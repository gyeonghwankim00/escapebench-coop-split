"""Actual Transformers regression, tiny random CPU model; no downloaded weights."""
import importlib.util
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.greedy_generation import generate_greedy, GENERATION_VERSION


@unittest.skipUnless(importlib.util.find_spec('transformers') and importlib.util.find_spec('torch'),
                     'Requires real transformers + torch (CPU suffices)')
class GreedyRegressionTests(unittest.TestCase):
    def model(self):
        import torch
        from transformers import GPT2Config, GPT2LMHeadModel, GenerationConfig
        torch.manual_seed(1)
        model = GPT2LMHeadModel(GPT2Config(vocab_size=16, n_positions=64,
            n_embd=8, n_layer=1, n_head=1, eos_token_id=15, bos_token_id=1)).eval()
        model.generation_config = GenerationConfig(do_sample=True, temperature=0.6, top_k=20,
            top_p=0.95, eos_token_id=15, pad_token_id=0, bos_token_id=1,
            transformers_version='4.51.3')
        return model

    def test_real_default_merge_reproduces_bug_and_guard_uses_greedy(self):
        import torch
        from transformers import GenerationConfig, StoppingCriteria, StoppingCriteriaList
        model = self.model()
        # This is what the old transport did: False is a global default and gets overwritten.
        broken, _ = model._prepare_generation_config(GenerationConfig(do_sample=False))
        self.assertTrue(broken.do_sample)

        class OneToken(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return torch.ones(input_ids.shape[0], dtype=torch.bool)

        inputs = dict(input_ids=torch.tensor([[1, 2], [1, 3]]), attention_mask=torch.ones((2, 2), dtype=torch.long))
        tok = SimpleNamespace(pad_token_id=0, eos_token_id=15, bos_token_id=1)
        with patch('torch.multinomial', side_effect=AssertionError('Sampling must never run')):
            out, audit = generate_greedy(model, inputs, tok, StoppingCriteriaList([OneToken()]))
        self.assertEqual(tuple(out.shape), (2, 3))
        self.assertEqual(audit['mode'], 'greedy_search')
        self.assertEqual(audit['version'], GENERATION_VERSION)
        self.assertFalse(audit['config']['do_sample'])
        self.assertEqual(audit['config']['temperature'], 1.0)  # neutral, unused for greedy
        self.assertNotIn('_prepare_generation_config', vars(model))

    def test_phi_architecture_and_multiple_end_tokens(self):
        import torch
        from transformers import Phi3Config, AutoModelForCausalLM, StoppingCriteria, StoppingCriteriaList
        config = Phi3Config(vocab_size=32, hidden_size=32, intermediate_size=64,
            num_hidden_layers=1, num_attention_heads=4, num_key_value_heads=2,
            max_position_embeddings=64, original_max_position_embeddings=64,
            eos_token_id=[1, 2], bos_token_id=1, pad_token_id=0)
        model = AutoModelForCausalLM.from_config(config, attn_implementation='sdpa').eval()
        class OneToken(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return torch.ones(input_ids.shape[0], dtype=torch.bool)
        with patch('torch.multinomial', side_effect=AssertionError('Sampling must never run')):
            result, audit = generate_greedy(model,
                dict(input_ids=torch.tensor([[5, 6]]), attention_mask=torch.ones((1, 2), dtype=torch.long)),
                SimpleNamespace(pad_token_id=0, eos_token_id=2, bos_token_id=1),
                StoppingCriteriaList([OneToken()]))
        self.assertEqual(tuple(result.shape), (1, 3))
        self.assertEqual(audit['config']['eos_token_id'], [1, 2])
        self.assertEqual(audit['mode'], 'greedy_search')

    def test_actual_preparation_drift_is_rejected_before_generation(self):
        import torch
        from transformers import StoppingCriteriaList
        model = self.model()
        original = model._prepare_generation_config
        def drift(config, use_model_defaults=None, **kwargs):
            effective, model_kwargs = original(config, use_model_defaults, **kwargs)
            effective.do_sample = True
            return effective, model_kwargs
        model._prepare_generation_config = drift
        with self.assertRaisesRegex(RuntimeError, 'Expected explicit greedy'):
            generate_greedy(model, dict(input_ids=torch.tensor([[1, 2]])),
                           SimpleNamespace(pad_token_id=0, eos_token_id=15, bos_token_id=1), StoppingCriteriaList())
        self.assertIs(model._prepare_generation_config, drift)


if __name__ == '__main__':
    unittest.main()
