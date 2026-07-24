# Training on Google Colab (free GPU)

Run the DQN training on Colab's GPU — it runs on Google's servers, so it keeps going
independent of your laptop, and it's much faster than CPU for the GRU/Transformer
models. The agent picks up the GPU automatically (`torch.device("cuda" …)`), so
**no code changes are needed**.

> **New notebook:** colab.research.google.com → New notebook →
> **Runtime ▸ Change runtime type ▸ Hardware accelerator = GPU (T4)** ▸ Save.

Paste each block below into its own cell and run top to bottom.

### 1. Confirm the GPU
```python
import torch
print("CUDA available:", torch.cuda.is_available())
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else
      "NO GPU — set Runtime ▸ Change runtime type ▸ GPU")
```

### 2. Mount Google Drive (so results survive when the session ends)
```python
from google.colab import drive
drive.mount('/content/drive')
import os; os.makedirs('/content/drive/MyDrive/roofsim', exist_ok=True)
```

### 3. Get the code
```python
!git clone https://github.com/AmitaiMyers/AmitaiRich.git
%cd AmitaiRich
```
*(Use `%cd`, not `!cd` — the `%` magic makes the directory stick across cells.)*

### 4. Install the one missing dep
Colab already ships PyTorch (with CUDA), NumPy and pandas. You only need yfinance:
```python
!pip install -q yfinance
```

### 5. Build the dataset once, cache it on Drive
Rebuilds from Drive on later sessions instead of re-downloading:
```python
import os, shutil
DRIVE = '/content/drive/MyDrive/roofsim'
os.makedirs('models', exist_ok=True)
if os.path.exists(f'{DRIVE}/daily_dataset.npz'):
    shutil.copy(f'{DRIVE}/daily_dataset.npz', 'models/daily_dataset.npz')
    print('restored dataset from Drive')
else:
    !python -m sim.agent.dataset            # downloads daily bars (~a few minutes)
    shutil.copy('models/daily_dataset.npz', f'{DRIVE}/daily_dataset.npz')
    print('built dataset and cached it to Drive')
```

### 6. Train on the GPU — writing results straight to Drive
Point `--out-dir` at Drive so the **best checkpoint + log survive even if the Colab
session drops** mid-run. Bigger `--batch-size` uses the GPU better.
```python
!python -m sim.agent.train_daily \
    --arch gru --window 30 --episodes 4000 --batch-size 256 \
    --indicators prices bollinger adx obv \
    --out-dir /content/drive/MyDrive/roofsim/runs/colab_gru
```

### 7. Validate + write the report
```python
!python -m sim.agent.validate \
    --model /content/drive/MyDrive/roofsim/runs/colab_gru/dqn_daily_best.pth \
    --ticker NVDA --csv /content/drive/MyDrive/roofsim/runs/colab_gru/tape_NVDA.csv
```
Your trained model, `train_log.csv`, and tape are now in
`Drive/MyDrive/roofsim/runs/colab_gru/`. Download the model to run locally:
```python
from google.colab import files
files.download('/content/drive/MyDrive/roofsim/runs/colab_gru/dqn_daily_best.pth')
```

### One command instead of steps 6–7 (train + validate + report)
```python
!python -m sim.agent.experiment --name colab_gru \
    --arch gru --window 30 --episodes 4000 --batch-size 256 \
    --indicators prices bollinger adx obv
!cp -r models/runs/colab_gru /content/drive/MyDrive/roofsim/runs/   # copy report bundle to Drive
```
(`experiment` writes to local `models/runs/`, so copy it to Drive afterwards — or use
step 6's `--out-dir` for live crash-safe checkpoints.)

---

## "Keep running when my computer is offline" — the honest limits

Colab runs on Google's servers, so **short disconnects are fine** and training keeps
going. But on the **free tier**:
- idle sessions disconnect after **~90 minutes**, and there's a **~12-hour** max;
- **closing the browser tab** can trigger the idle timeout, so a fully-offline laptop
  for hours isn't guaranteed to keep the session alive.

Mitigations:
- **Write checkpoints to Drive** (step 6's `--out-dir`) so a drop never loses the best
  model — just re-run the cell to resume a fresh run from the cached dataset.
- Keep runs within the window (e.g. a few thousand episodes) and validate as you go
  (the best model is saved whenever validation improves).
- For truly unattended, long, background runs, use **Colab Pro / Pro+** (longer
  runtimes + background execution) — or a cloud VM with a GPU.

## Notes
- **GPU speedup** is largest for `--arch gru`/`transformer`, bigger `--d-model`, and
  bigger `--batch-size`; the tiny `mlp` is partly CPU-bound (the env steps in Python),
  so its gain is smaller. Increase batch size / episodes to make the GPU earn its keep.
- The live progress bar renders in Colab cell output (carriage-return updates).
- The **Agent Lab GUI** is a local web app — for Colab, use these CLI commands. (You
  can review a downloaded run's `report.md` locally, or run `python -m sim.server`
  on your machine to browse `models/runs/` in the GUI.)
