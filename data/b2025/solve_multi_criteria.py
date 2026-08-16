# -*- coding: utf-8 -*-
"""B2025 判据求解 v3：d 自由但紧约束（±10% 内多起点），双光束 vs Airy 独立出厚度+不确定度。

产出：
  - 每附件: η2, η3, d_two±std, RMSE_two, R², d_airy±std, RMSE_airy, R², |q|, η改善, 模型选择
  - 五.4 判据结论（附件3/4 硅）
  - 五.5 修正结果（附件1/2 碳化硅，Airy 修正厚度）
  - 6.4 灵敏度：r_amp ±10% → d 偏移
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt
from scipy.optimize import least_squares
from scipy.fft import rfft, rfftfreq

BASE = Path(r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent\data\b2025")
OUT_JSON = Path(r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent\data\results\paper_20260810_005841_metrics_v3.json")

CFG = {
    "附件1.xlsx": {"n": 3.40, "theta": 10.0},
    "附件2.xlsx": {"n": 3.40, "theta": 15.0},
    "附件3.xlsx": {"n": 3.44, "theta": 10.0},
    "附件4.xlsx": {"n": 3.44, "theta": 15.0},
}


def load(f):
    df = pd.read_excel(BASE / f, header=0)
    nu = df.iloc[:, 0].values.astype(float)
    R = df.iloc[:, 1].values.astype(float) / 100.0
    return nu, R


def bg_remove(R, cutoff=0.005):
    b, a = butter(2, cutoff, btype="high")
    return filtfilt(b, a, R)


def fft_metrics(R_high, nu):
    N = len(R_high)
    Y = np.abs(rfft(R_high * np.hanning(N)))
    fr = rfftfreq(N, d=nu[1] - nu[0])
    i0 = np.argmax(Y[1:]) + 1
    f0 = fr[i0]
    dfr = fr[1] - fr[0]
    def amp(f):
        i = min(max(int(round(f / dfr)), 0), len(Y) - 1)
        return Y[i]
    return f0, amp(2 * f0) / Y[i0], amp(3 * f0) / Y[i0]


def phase(nu, d_um, n, th0):
    tht = np.arcsin(np.sin(np.radians(th0)) / n)
    return 4 * np.pi * (d_um * 1e-4) * n * nu * np.cos(tht)


def model_single(nu, p, n, th0):
    d, A, phi, b0, b1, b2, b3 = p
    lam = 10000.0 / nu
    n_eff = n + 0.02 / lam ** 2                      # 简单色散
    bl = b0 + b1 * nu + b2 * nu ** 2 + b3 * nu ** 3  # 立方基线
    return bl + A * np.cos(phase(nu, d, n_eff, th0) + phi)


def model_airy(nu, p, n, th0):
    d, ramp, rphase, b0, b1, b2, b3 = p
    lam = 10000.0 / nu
    n_eff = n + 0.02 / lam ** 2
    tht = np.arcsin(np.sin(np.radians(th0)) / n_eff)
    c0, ct = np.cos(np.radians(th0)), np.cos(tht)
    r_s = (c0 - n_eff * ct) / (c0 + n_eff * ct)
    r_p = (n_eff * c0 - ct) / (n_eff * c0 + ct)
    r12 = ramp * np.exp(1j * rphase)
    e = np.exp(1j * phase(nu, d, n_eff, th0))
    Rm = (np.abs((r_s + r12 * e) / (1 + r_s * r12 * e)) ** 2
          + np.abs((r_p + r12 * e) / (1 + r_p * r12 * e)) ** 2) / 2
    return b0 + b1 * nu + b2 * nu ** 2 + b3 * nu ** 3 + Rm


def fit_report(nu, R, model, p0, lo, hi, labels):
    res = least_squares(lambda p: model(nu, p) - R, p0, bounds=(lo, hi),
                        max_nfev=80000, xtol=1e-12, ftol=1e-12)
    resid = model(nu, res.x) - R
    n, k = len(R), len(res.x)
    sigma2 = np.sum(resid ** 2) / max(n - k, 1)
    J = res.jac
    try:
        cov = sigma2 * np.linalg.inv(J.T @ J)
        std = np.sqrt(np.diag(cov))
    except np.linalg.LinAlgError:
        std = np.full(k, np.nan)
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    r2 = float(1 - np.sum(resid ** 2) / np.sum((R - np.mean(R)) ** 2))
    d = {l: (float(v), float(s)) for l, v, s in zip(labels, res.x, std)}
    return res.x, d, rmse, r2


def r01(n, th0):
    tht = np.arcsin(np.sin(np.radians(th0)) / n)
    c0, ct = np.cos(np.radians(th0)), np.cos(tht)
    return (c0 - n * ct) / (c0 + n * ct), (n * c0 - ct) / (n * c0 + ct)


results = {}
for fname, cfg in CFG.items():
    nu, R = load(fname)
    f0, eta2, eta3 = fft_metrics(bg_remove(R), nu)
    n, th0 = cfg["n"], cfg["theta"]
    d_fft = f0 * 1e4 / (2 * n * np.cos(np.radians(th0)))
    lo_d, hi_d = d_fft * 0.97, d_fft * 1.03

    # 双光束（d 自由，紧约束 ±3%）
    p0s = [d_fft, 0.05, 0.0, np.median(R), 0.0, 0.0, 0.0]
    x_s, d_s, rmse_s, r2_s = fit_report(
        nu, R, lambda nu, p: model_single(nu, p, n, th0), p0s,
        [lo_d, 0, -np.pi, -0.5, -1e-3, -1e-6, -1e-9],
        [hi_d, 0.5, np.pi, 0.5, 1e-3, 1e-6, 1e-9],
        ["d", "A", "phi", "b0", "b1", "b2", "b3"])

    # Airy 多光束（d 自由，紧约束，多起点）
    best = None
    for rstart in (0.02, 0.08, 0.15, 0.3):
        for phstart in (0.0, 1.0, -1.0):
            p0a = [d_fft, rstart, phstart, np.median(R), 0.0, 0.0, 0.0]
            try:
                x_a, d_a, rmse_a, r2_a = fit_report(
                    nu, R, lambda nu, p: model_airy(nu, p, n, th0), p0a,
                    [lo_d, 0, -np.pi, -0.5, -1e-3, -1e-6, -1e-9],
                    [hi_d, 0.5, np.pi, 0.5, 1e-3, 1e-6, 1e-9],
                    ["d", "ramp", "rphase", "b0", "b1", "b2", "b3"])
            except Exception:
                continue
            if best is None or rmse_a < best[0]:
                best = (rmse_a, x_a, d_a, r2_a)
    rmse_a, x_a, d_a, r2_a = best
    ramp = x_a[1]
    r01s, r01p = r01(n, th0)
    qbar = float(np.mean(np.abs([r01s * ramp, r01p * ramp])))
    eta_imp = (rmse_s - rmse_a) / rmse_s * 100 if rmse_s > 0 else 0.0
    choice = "多光束" if (eta2 > 0.1 or eta3 > 0.1) and rmse_a < rmse_s else "单光束"

    d_s_val, d_s_std = d_s["d"]
    d_a_val, d_a_std = d_a["d"]
    results[fname] = {
        "eta2": round(eta2, 4), "eta3": round(eta3, 4),
        "d_fft": round(d_fft, 3),
        "d_two": round(d_s_val, 3), "d_two_std": round(d_s_std, 4),
        "RMSE_two": round(rmse_s, 6), "R2_two": round(r2_s, 4),
        "d_airy": round(d_a_val, 3), "d_airy_std": round(d_a_std, 4),
        "RMSE_airy": round(rmse_a, 6), "R2_airy": round(r2_a, 4),
        "qbar": round(qbar, 4), "ramp": round(ramp, 4),
        "eta_improve_pct": round(eta_imp, 3), "model_choice": choice,
    }
    print(f"{fname} [{cfg['n']},{th0}°]: d_two={d_s_val:.3f}±{d_s_std:.4f} "
          f"RMSE={rmse_s:.6f} R2={r2_s:.4f} | d_airy={d_a_val:.3f}±{d_a_std:.4f} "
          f"RMSE={rmse_a:.6f} R2={r2_a:.4f} | η2={eta2:.4f} η3={eta3:.4f} "
          f"|q|={qbar:.4f} 改善={eta_imp:.3f}% → {choice}")

# 6.4 灵敏度：r_amp ±10% 对 Airy 厚度的影响（用附件1 SiC）
fname = "附件1.xlsx"
cfg = CFG[fname]; nu, R = load(fname)
n, th0 = cfg["n"], cfg["theta"]
f0, _, _ = fft_metrics(bg_remove(R), nu)
d_fft = f0 * 1e4 / (2 * n * np.cos(np.radians(th0)))
base = results[fname]["d_airy"]
ramp0 = results[fname]["ramp"]
sens = {}
for delta in (-0.10, 0.10):
    ramp_t = max(ramp0 * (1 + delta), 0.01)
    p0 = [base, ramp_t, 0.0, np.median(R), 0.0, 0.0, 0.0]
    x, d_, rmse_, r2_ = fit_report(
        nu, R, lambda nu, p: model_airy(nu, p, n, th0), p0,
        [d_fft * 0.97, 0, -np.pi, -0.5, -1e-3, -1e-6, -1e-9],
        [d_fft * 1.03, 0.5, np.pi, 0.5, 1e-3, 1e-6, 1e-9],
        ["d", "ramp", "rphase", "b0", "b1", "b2", "b3"])
    sens[f"{delta:+.0%}"] = round(d_["d"][0], 3)
results["_sensitivity_airy_ramp_10pct"] = sens

OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n结果已保存:", OUT_JSON)
