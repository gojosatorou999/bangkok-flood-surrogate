"""Zero-shot CLIP model + text-embedding setup. See docs/VARUN_IMPLEMENTATION.md §6 T50.

Loading this module downloads/loads the ViT-B-32 laion2b_s34b_b79k
checkpoint (cached by open_clip/huggingface_hub after the first run) and
encodes the class prompts once at import time.
"""
import open_clip
import torch

from .prompts import PROMPTS

MODEL, PRETRAINED = "ViT-B-32", "laion2b_s34b_b79k"
CLASSES = list(PROMPTS)

_dev = "cuda" if torch.cuda.is_available() else "cpu"
_model, _, _pre = open_clip.create_model_and_transforms(MODEL, pretrained=PRETRAINED)
_model = _model.to(_dev).eval()
_tok = open_clip.get_tokenizer(MODEL)

with torch.no_grad():
    _T = torch.stack(
        [
            torch.nn.functional.normalize(_model.encode_text(_tok(PROMPTS[c]).to(_dev)).float(), dim=-1).mean(0)
            for c in CLASSES
        ]
    )
    _T = torch.nn.functional.normalize(_T, dim=-1)


def embed_and_zeroshot(pil_images):
    """Returns (embeddings: np.ndarray (N, 512), probs: np.ndarray (N, len(CLASSES)))."""
    x = torch.stack([_pre(im) for im in pil_images]).to(_dev)
    with torch.no_grad():
        f = torch.nn.functional.normalize(_model.encode_image(x).float(), dim=-1)
        p = (100.0 * f @ _T.T).softmax(-1)
    return f.cpu().numpy(), p.cpu().numpy()
