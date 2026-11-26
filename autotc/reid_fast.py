"""Penyandi ReID cepat untuk BoT-SORT.

Bawaan Ultralytics untuk model YOLO26 (end-to-end) memakai `yolo26n-cls.pt` lewat predictor biasa:
setiap potongan kendaraan diproses satu per satu di CPU sebelum masuk GPU. Dengan detektor TensorRT,
bagian ini menjadi yang paling lambat. Di sini semua potongan satu frame diambil sekaligus di GPU
(roi_align) lalu dilewatkan ke tulang punggung model yang sama; ciri = rata-rata peta fitur lapisan
sebelum kepala klasifikasi, sama seperti `YOLO.embed`. Tulang punggung dijalankan dengan TensorRT bila
mesinnya sudah dibuat (`build_engine`), selain itu dengan PyTorch FP16.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from torchvision.ops import roi_align

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = ROOT / "model" / "yolo26n-cls.pt"
ENGINE = ROOT / "model" / "reid_yolo26n_224.engine"
SIZE = 224
MAX_BATCH = 128


class _Backbone(torch.nn.Module):
    def __init__(self, weights):
        super().__init__()
        from ultralytics import YOLO
        self.net = torch.nn.Sequential(*YOLO(str(weights)).model.model[:-1])   # tanpa kepala klasifikasi

    def forward(self, x):
        return self.net(x).mean((2, 3))


def build_engine(weights: str | Path = WEIGHTS, out: str | Path = ENGINE) -> Path:
    """Buat mesin TensorRT FP16 untuk tulang punggung ReID (ukuran batch 1..MAX_BATCH). Sekali saja."""
    import tensorrt as trt
    out = Path(out)
    onnx = out.with_suffix(".onnx")
    m = _Backbone(weights).eval().cuda().half()     # TensorRT 11: presisi mengikuti tipe data ONNX
    for p in m.parameters():
        p.requires_grad_(False)
    x = torch.zeros(4, 3, SIZE, SIZE, device="cuda", dtype=torch.float16)
    torch.onnx.export(m, x, str(onnx), input_names=["x"], output_names=["f"], opset_version=17,
                      dynamic_axes={"x": {0: "n"}, "f": {0: "n"}}, dynamo=False)
    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    flags = 0
    if hasattr(trt.NetworkDefinitionCreationFlag, "STRONGLY_TYPED"):
        flags = 1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED)
    net = builder.create_network(flags)
    parser = trt.OnnxParser(net, logger)
    if not parser.parse(onnx.read_bytes()):
        raise RuntimeError("ONNX ReID gagal dibaca: " + "; ".join(str(parser.get_error(i)) for i in range(parser.num_errors)))
    cfg = builder.create_builder_config()
    if hasattr(trt.BuilderFlag, "FP16") and not flags:
        cfg.set_flag(trt.BuilderFlag.FP16)
    prof = builder.create_optimization_profile()
    prof.set_shape("x", (1, 3, SIZE, SIZE), (16, 3, SIZE, SIZE), (MAX_BATCH, 3, SIZE, SIZE))
    cfg.add_optimization_profile(prof)
    data = builder.build_serialized_network(net, cfg)
    if data is None:
        raise RuntimeError("Mesin TensorRT ReID gagal dibuat.")
    out.write_bytes(bytes(data))
    onnx.unlink(missing_ok=True)
    return out


class _TRT:
    def __init__(self, path: Path, device):
        import tensorrt as trt
        self.device = device
        self.engine = trt.Runtime(trt.Logger(trt.Logger.WARNING)).deserialize_cuda_engine(path.read_bytes())
        self.ctx = self.engine.create_execution_context()
        self.dim = self.engine.get_tensor_shape("f")[1]
        to_torch = {trt.DataType.HALF: torch.float16, trt.DataType.FLOAT: torch.float32}
        self.in_dtype = to_torch[self.engine.get_tensor_dtype("x")]
        self.out_dtype = to_torch[self.engine.get_tensor_dtype("f")]
        self.stream = torch.cuda.Stream(device)

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        outs = []
        for s in range(0, len(x), MAX_BATCH):
            chunk = x[s:s + MAX_BATCH].to(self.in_dtype).contiguous()
            out = torch.empty((len(chunk), self.dim), dtype=self.out_dtype, device=self.device)
            self.ctx.set_input_shape("x", tuple(chunk.shape))
            self.ctx.set_tensor_address("x", chunk.data_ptr())
            self.ctx.set_tensor_address("f", out.data_ptr())
            self.stream.wait_stream(torch.cuda.current_stream(self.device))
            self.ctx.execute_async_v3(self.stream.cuda_stream)
            torch.cuda.current_stream(self.device).wait_stream(self.stream)
            outs.append(out.float())
        return torch.cat(outs)


class FastReID:
    def __init__(self, weights: str | Path = WEIGHTS, device=None, engine: bool = True):
        self.device = torch.device(device if device is not None else ("cuda" if torch.cuda.is_available() else "cpu"))
        if self.device.type == "cuda" and self.device.index is None:
            self.device = torch.device("cuda", torch.cuda.current_device())
        self.run = None
        if engine and self.device.type == "cuda" and ENGINE.exists():
            try:
                self.run = _TRT(ENGINE, self.device)
            except Exception:   # mesin dari kartu grafis/driver lain: pakai PyTorch
                self.run = None
        if self.run is None:
            net = _Backbone(weights).to(self.device).eval()
            if self.device.type == "cuda":
                net = net.half()
            self.run = lambda x: net(x.half() if self.device.type == "cuda" else x).float()

    @torch.inference_mode()
    def __call__(self, img: np.ndarray, dets: np.ndarray) -> list[np.ndarray | None]:
        if len(dets) == 0:
            return []
        h, w = img.shape[:2]
        xywh = torch.as_tensor(dets[:, :4], dtype=torch.float32)
        x1 = (xywh[:, 0] - xywh[:, 2] / 2).clamp(0, w)
        y1 = (xywh[:, 1] - xywh[:, 3] / 2).clamp(0, h)
        x2 = (xywh[:, 0] + xywh[:, 2] / 2).clamp(0, w)
        y2 = (xywh[:, 1] + xywh[:, 3] / 2).clamp(0, h)
        valid = ((x2 - x1) >= 1) & ((y2 - y1) >= 1)
        if not valid.any():
            return [None] * len(dets)
        # hanya bagian frame yang memuat kendaraan yang dikirim ke GPU
        bx1, by1 = int(x1[valid].min()), int(y1[valid].min())
        bx2, by2 = int(np.ceil(float(x2[valid].max()))), int(np.ceil(float(y2[valid].max())))
        part = torch.from_numpy(np.ascontiguousarray(img[by1:by2, bx1:bx2])).to(self.device, non_blocking=True)
        part = part.permute(2, 0, 1).flip(0).unsqueeze(0).float().div_(255)    # BGR -> RGB, 1x3xHxW
        boxes = torch.stack([torch.zeros_like(x1), x1 - bx1, y1 - by1, x2 - bx1, y2 - by1], 1)[valid].to(self.device)
        crops = roi_align(part, boxes, (SIZE, SIZE), spatial_scale=1.0, sampling_ratio=2, aligned=True)
        feats = self.run(crops).cpu().numpy()
        it = iter(feats)
        return [next(it) if ok else None for ok in valid.tolist()]


_installed = False


def install():
    """Ganti penyandi ReID bawaan BoT-SORT (yang memakai yolo26n-cls.pt) dengan versi cepat ini."""
    global _installed
    if _installed:
        return
    from ultralytics.trackers import bot_sort
    original = bot_sort.build_encoder

    def build_encoder(with_reid, model, device=None):
        if with_reid and model and Path(str(model)).name == "yolo26n-cls.pt":
            return FastReID(WEIGHTS if WEIGHTS.exists() else model, device)
        return original(with_reid, model, device)

    bot_sort.build_encoder = build_encoder
    _installed = True
