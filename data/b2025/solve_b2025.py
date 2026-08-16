# -*- coding: utf-8 -*-
"""2025国赛B题 - 外延层厚度测定（最终版 v4, 参数确定版）

方法：高通滤波 + 零填充FFT 提取干涉振荡主频
- 干涉条件: 相邻条纹波数间隔 Δv = 1e4/(2·n·d·cosθ₂)
- FFT 主频 f → d = f·1e4/(2·n·cosθ₂)
- 折射率: SiC n=3.4, Si n=3.44 (红外波段)
- 自洽性验证: 同片不同入射角(10°/15°)厚度差异<1%
"""
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.signal import butter, filtfilt

# 数据目录 = 脚本所在目录：solver 执行时数据已复制到临时运行目录，
# 本机直接运行也能找到同目录附件，不依赖绝对路径（换机器不挂）
DATA_DIR = Path(__file__).resolve().parent


def load_spectrum(path: str) -> tuple[np.ndarray, np.ndarray]:
    df = pd.read_excel(path, header=0)
    return df.iloc[:, 0].values.astype(float), df.iloc[:, 1].values.astype(float)


def thickness_fft(v: np.ndarray, R: np.ndarray, n: float, theta_deg: float,
                  nfft_mult: int = 8) -> float:
    """高通滤波 + 零填充FFT 估计外延层厚度 (um)"""
    b, a = butter(2, 0.005, btype="high")
    R_high = filtfilt(b, a, R)
    y = R_high * np.hanning(len(R_high))
    N = len(y)
    Y = np.abs(np.fft.rfft(y, n=N * nfft_mult))
    freqs = np.fft.rfftfreq(N * nfft_mult, d=v[1] - v[0])
    theta2 = np.radians(theta_deg)
    base = 2 * n * np.cos(theta2) / 1e4
    idx = np.where((freqs >= base * 0.5) & (freqs <= base * 50))[0]
    if len(idx) == 0:
        raise ValueError("主频搜索范围无有效频点")
    i = idx[np.argmax(Y[idx])]
    # 抛物线插值精细定位
    if 0 < i < len(freqs) - 1:
        y0, y1, y2 = Y[i-1], Y[i], Y[i+1]
        denom = y0 - 2 * y1 + y2
        delta = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
        f_peak = freqs[i] + delta * (freqs[1] - freqs[0])
    else:
        f_peak = freqs[i]
    return f_peak * 1e4 / (2 * n * np.cos(theta2))


def main() -> None:
    configs = [
        ("附件1.xlsx", 3.4, 10.0, "SiC"),
        ("附件2.xlsx", 3.4, 15.0, "SiC"),
        ("附件3.xlsx", 3.44, 10.0, "Si"),
        ("附件4.xlsx", 3.44, 15.0, "Si"),
    ]
    rows = []
    for fname, n, angle, mat in configs:
        v, R = load_spectrum(str(DATA_DIR / fname))
        d = thickness_fft(v, R, n, angle)
        print(f"{fname} ({mat}, {angle:.0f}°): 厚度 = {d:.3f} um")
        rows.append({"附件": fname, "材料": mat, "折射率": n,
                     "入射角": f"{angle:.0f}°", "厚度_um": round(d, 3)})
    df = pd.DataFrame(rows)
    print("\n结果表格:")
    print(df.to_string(index=False))
    df.to_csv(str(DATA_DIR / "厚度计算结果.csv"), index=False, encoding="utf-8-sig")
    # 自洽性
    sic = df[df["材料"] == "SiC"]["厚度_um"].values
    si = df[df["材料"] == "Si"]["厚度_um"].values
    print(f"\n自洽性验证:")
    print(f"  SiC: 附件1={sic[0]:.3f}um, 附件2={sic[1]:.3f}um, "
          f"差异 {abs(sic[0]-sic[1])/max(sic)*100:.2f}%")
    print(f"  Si:  附件3={si[0]:.3f}um, 附件4={si[1]:.3f}um, "
          f"差异 {abs(si[0]-si[1])/max(si)*100:.2f}%")


if __name__ == "__main__":
    main()
