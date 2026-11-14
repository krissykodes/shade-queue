"""Validation figure: LiDAR-measured crowns vs USFS UTD allometric predictions (Mott Haven, 2021 LiDAR)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

l = pd.read_parquet("data/interim/mott_haven/lidar_crowns.parquet")
top = l.species.value_counts().index[:5]
fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), dpi=150)
for ax, (meas, pred, label) in zip(axes, [("height_m", "allometric_height_m", "Tree height (m)"),
                                         ("crown_radius_m", "allometric_radius_m", "Crown radius (m)")]):
    other = ~l.species.isin(top)
    ax.scatter(l.loc[other, pred], l.loc[other, meas], s=8, c="#b9c2bc", label="other species", lw=0)
    for sp, col in zip(top, ["#2f7d4f", "#e07b26", "#24476b", "#a33b6a", "#8aa65b"]):
        m = l.species == sp
        ax.scatter(l.loc[m, pred], l.loc[m, meas], s=10, c=col, label=sp, lw=0, alpha=.85)
    hi = max(l[meas].max(), l[pred].max()) * 1.05
    ax.plot([0, hi], [0, hi], ls="--", c="#888", lw=1)
    r = np.corrcoef(l[pred], l[meas])[0, 1]
    ax.set(xlabel=f"Allometric prediction from DBH", ylabel="LiDAR measured", title=f"{label}  (r = {r:.2f}, n = {len(l)})",
           xlim=(0, hi), ylim=(0, hi))
    ax.spines[["top", "right"]].set_visible(False)
axes[0].legend(fontsize=7, frameon=False, loc="upper left")
fig.suptitle("Mott Haven street trees: 2021 LiDAR crowns vs USFS Urban Tree Database (Queens) allometry", fontsize=10)
fig.tight_layout()
fig.savefig("docs/figures/lidar_vs_allometric.png")
print("wrote docs/figures/lidar_vs_allometric.png")
