import os
import json
from typing import List, Dict, Any, Optional
import torch

class SimpleProductionTokenizer:
    """
    Byte-level fallback and vocabulary mapping tokenizer for production deployment.
    """
    def __init__(self, vocab: Optional[Dict[str, int]] = None):
        if vocab is not None:
            self.vocab = vocab
        else:
            # Standard ASCII + byte mapping
            self.vocab = {"<pad>": 0, "<bos>": 1, "<eos>": 2, "<unk>": 3}
            for i in range(256):
                char = chr(i)
                if char not in self.vocab:
                    self.vocab[char] = len(self.vocab)
        self.inv_vocab = {v: k for k, v in self.vocab.items()}

    def encode(self, text: str, add_bos: bool = True) -> List[int]:
        tokens = [self.vocab["<bos>"]] if add_bos else []
        for char in text:
            tokens.append(self.vocab.get(char, self.vocab["<unk>"]))
        return tokens

    def decode(self, token_ids: List[int], skip_special: bool = True) -> str:
        chars = []
        special_ids = {0, 1, 2, 3}
        for tid in token_ids:
            if skip_special and tid in special_ids:
                continue
            chars.append(self.inv_vocab.get(tid, ""))
        return "".join(chars)

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.vocab, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "SimpleProductionTokenizer":
        with open(path, "r", encoding="utf-8") as f:
            vocab = json.load(f)
        return cls(vocab=vocab)


class FractalHoloNetInferencePipeline:
    """
    High-level production inference pipeline for text completion and embedding extraction.
    """
    def __init__(self, model_dir: str, device: str = "cpu"):
        from fractal_holonet_prod import ProductionFractalHoloNet
        self.device = torch.device(device)
        self.model = ProductionFractalHoloNet.from_pretrained(model_dir, map_location=device)
        self.model.to(self.device)
        self.model.eval()
        
        tokenizer_path = os.path.join(model_dir, "tokenizer.json")
        if os.path.exists(tokenizer_path):
            self.tokenizer = SimpleProductionTokenizer.load(tokenizer_path)
        else:
            self.tokenizer = SimpleProductionTokenizer()

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 64,
        temperature: float = 0.8,
        top_k: int = 40,
        top_p: float = 0.9
    ) -> Dict[str, Any]:
        input_ids = torch.tensor([self.tokenizer.encode(prompt)], dtype=torch.long, device=self.device)
        prompt_len = input_ids.size(1)
        
        output_ids = self.model.generate(
            prompt_ids=input_ids,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p
        )
        
        generated_ids = output_ids[0].tolist()
        new_ids = generated_ids[prompt_len:]
        full_text = self.tokenizer.decode(generated_ids)
        new_text = self.tokenizer.decode(new_ids)
        
        return {
            "prompt": prompt,
            "generated_text": new_text,
            "full_text": full_text,
            "prompt_tokens": prompt_len,
            "generated_tokens": len(new_ids),
        }

    def get_embeddings(self, text: str) -> List[float]:
        input_ids = torch.tensor([self.tokenizer.encode(text, add_bos=True)], dtype=torch.long, device=self.device)
        with torch.no_grad():
            x = self.model.token_emb(input_ids)
            for block in self.model.blocks:
                x, _ = block(x)
            x = self.model.ln_f(x)
            # Mean pooling
            emb = x.mean(dim=1).squeeze(0).cpu().tolist()
        return emb
