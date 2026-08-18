import os
import json
from typing import List, Dict, Any, Optional
import torch

class SimpleProductionTokenizer:
    """
    Byte-level UTF-8 production tokenizer with support for Cyrillic and multilingual text.
    """
    def __init__(self, vocab: Optional[Dict[str, int]] = None):
        if vocab is not None:
            self.vocab = vocab
        else:
            self.vocab = {"<pad>": 0, "<bos>": 1, "<eos>": 2, "<unk>": 3}
            for b in range(256):
                token_key = f"<byte_{b}>"
                if token_key not in self.vocab:
                    self.vocab[token_key] = len(self.vocab)
        self.inv_vocab = {v: k for k, v in self.vocab.items()}

    def encode(self, text: str, add_bos: bool = False) -> List[int]:
        tokens = [self.vocab["<bos>"]] if add_bos else []
        byte_data = text.encode("utf-8")
        for b in byte_data:
            token_key = f"<byte_{b}>"
            tokens.append(self.vocab.get(token_key, self.vocab["<unk>"]))
        return tokens

    def decode(self, token_ids: List[int], skip_special: bool = True) -> str:
        byte_list = []
        special_ids = {0, 1, 2, 3}
        for tid in token_ids:
            if skip_special and tid in special_ids:
                continue
            token_str = self.inv_vocab.get(tid, "")
            if token_str.startswith("<byte_") and token_str.endswith(">"):
                try:
                    b = int(token_str[6:-1])
                    byte_list.append(b)
                except ValueError:
                    pass
        return bytes(byte_list).decode("utf-8", errors="replace")

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
        from holonet.models.fractal_holonet import ProductionFractalHoloNet
        self.device = torch.device(device)
        self.model = ProductionFractalHoloNet.from_pretrained(model_dir, map_location=device)
        self.model.to(self.device)
        self.model.eval()
        
        tok_path = os.path.join(model_dir, "tokenizer.json")
        if os.path.exists(tok_path):
            self.tokenizer = SimpleProductionTokenizer.load(tok_path)
        else:
            self.tokenizer = SimpleProductionTokenizer()

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 50,
        temperature: float = 0.7,
        top_k: int = 40,
        top_p: float = 0.9
    ) -> Dict[str, Any]:
        prompt_ids = self.tokenizer.encode(prompt, add_bos=True)
        inp = torch.tensor([prompt_ids], dtype=torch.long, device=self.device)
        
        out_ids = self.model.generate(
            inp,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p
        )
        
        gen_tokens = out_ids[0].tolist()
        gen_text = self.tokenizer.decode(gen_tokens[len(prompt_ids):])
        full_text = self.tokenizer.decode(gen_tokens)
        
        return {
            "prompt": prompt,
            "generated_text": gen_text,
            "full_text": full_text,
            "prompt_tokens": len(prompt_ids),
            "generated_tokens": len(gen_tokens) - len(prompt_ids)
        }

    def get_embeddings(self, text: str) -> List[float]:
        prompt_ids = self.tokenizer.encode(text, add_bos=False)
        inp = torch.tensor([prompt_ids], dtype=torch.long, device=self.device)
        with torch.no_grad():
            x = self.model.token_emb(inp)
            for block in self.model.blocks:
                x, _ = block(x)
            emb = self.model.ln_f(x).mean(dim=1).squeeze(0)
            return emb.cpu().tolist()
