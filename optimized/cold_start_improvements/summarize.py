"""Print concise results and save a comparison chart after an experiment."""
import argparse

from optimized.cold_start_benchmark.experiment import pd, json
from .experiment import HERE, report


def summarize(run_dir):
    if not (run_dir/"completed.json").exists():
        raise ValueError("Experiment is not complete")
    table=pd.read_csv(run_dir/"comparison.csv")
    report(run_dir,table.to_dict(orient="records"),
           json.loads((run_dir/"selection.json").read_text(encoding="utf-8")),
           json.loads((run_dir/"paired_uncertainty.json").read_text(encoding="utf-8")))
    print(table[["scope","variant","model","diversity_weight","evaluated_users",
                 "recall@10","ndcg@10","recommended_items","candidate_items","unique_brands@10"]].to_string(index=False))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    subset=table.loc[table.variant.isin(["baseline","selected"])]
    fig,axes=plt.subplots(1,3,figsize=(16,4.5))
    for ax,column,label in [(axes[0],"ndcg@10","NDCG@10 (within each scope)"),
                            (axes[1],"unique_brands@10","Mean unique brands per top 10"),
                            (axes[2],"catalogue_coverage_at_10","Catalogue coverage@10")]:
        subset.pivot(index="scope",columns="variant",values=column).plot.bar(ax=ax,color=["#8a9baa","#267b68"],rot=20)
        ax.set_xlabel("")
        ax.set_ylabel(label)
        ax.grid(axis="y",alpha=.2)
    fig.suptitle("Cold-user follow-up: same held-out users, validation-selected policies")
    fig.tight_layout()
    fig.savefig(run_dir/"comparison.png",dpi=160)
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name",default="improvements_v1")
    args=parser.parse_args()
    from pathlib import Path
    if Path(args.run_name).name != args.run_name or args.run_name in (".",".."):
        parser.error("run-name must be a single folder name")
    summarize(HERE/"artifacts"/args.run_name)


if __name__=="__main__":
    main()
