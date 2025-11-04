import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd

from matplotlib.font_manager import fontManager, FontProperties

path = "../assets/fonts/inter.ttf"
fontManager.addfont(path)

prop = FontProperties(fname=path)

sns.set_theme(
    font=prop.get_name(),
    rc={
    'axes.facecolor': '#0c2c14',
    'figure.facecolor':'#0c2c14',
    "text.color": '#ffffff',        # all text fallback
    "axes.titlecolor": '#ffffff',   # title
    "axes.labelcolor": '#ffffff',   # x/y labels
    "xtick.color": '#ffffffff',
    "ytick.color": '#ffffffff',
    "axes.edgecolor": 'none',
    "patch.edgecolor": 'none',
    "grid.color": '#092310',
})
sns.set_palette(["#568a63", "#fd663a", "#9b85b2", "#73762b", "#5a5485"])

# Example wide-form data
df = pd.DataFrame({
    "Inline": [3240, 5669, 2316],
    "Pipeline": [4433, 5563, 2349],
}, index=["AMD Radeon RX 9070 XT", "NVIDIA Geforce RTX 5070 Ti", "Intel Arc B580"])

print(df)

# Convert wide-form to long-form (tidy)
df_long = df.reset_index().melt(id_vars="index", 
                                var_name="Category", 
                                value_name="Ray Tracing Score")

print(df_long)


# Plot
fig, ax = plt.subplots()
ax = sns.barplot(
    data=df_long,
    x="index",
    y="Ray Tracing Score",
    hue="Category",
    ax=ax,
    )

ax.set_xlabel("")

def change_width(ax, new_value) :
    for patch in ax.patches :
        current_width = patch.get_width()
        diff = current_width - new_value

        # we change the bar width
        patch.set_width(new_value)

        # we recenter the bar
        patch.set_x(patch.get_x() + diff * .5)
        


def change_height(ax, new_value) :
    for patch in ax.patches :
        current_height = patch.get_height()
        diff = current_height - new_value

        # we change the bar height
        patch.set_height(new_value)

        # we recenter the bar
        patch.set_y(patch.get_y() + diff * .5)

# plt.xlabel("GPU")
# plt.ylabel("Score")
plt.title("Inline vs Pipeline Ray Tracing")
# plt.legend(title="Evolve Scores")
plt.savefig("test.png")
plt.show()
