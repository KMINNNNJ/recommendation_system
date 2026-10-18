"""Exercise preprocessing, all models, serialization and evaluation on fake data."""
from pathlib import Path
import tempfile
import uuid

import numpy as np
import pandas as pd

from optimized.cold_start_benchmark.experiment import main


def run():
    import sys
    rng=np.random.default_rng(42)
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        items=30
        pd.DataFrame({
            "product_id":[f"p{i:02}" for i in range(items)],
            "product_name":[f"Fake product {i}" for i in range(items)],
            "primary_category":["Skincare"]*items,
            "brand_name":[f"brand{i%3}" for i in range(items)],
            "secondary_category":["Moisturizers"]*items,
            "tertiary_category":["Cream"]*items,
            "variation_type":["Size"]*items,
            "price_usd":rng.integers(10,100,items),
            "ingredients":["['water, glycerin, panthenol']"]*items,
        }).to_csv(root/"product_info.csv",index=False)
        rows=[]
        for user in range(500):
            for item in rng.choice(items,size=4,replace=False):
                rating=5 if (item%3==user%3 or rng.random()<.3) else 1
                rows.append({"author_id":f"u{user:04}","product_id":f"p{item:02}",
                             "submission_time":"2022-01-01","rating":rating,"is_recommended":int(rating==5),
                             "skin_type":["dry","oily","normal"][user%3],
                             "skin_tone":"light","eye_color":"brown","hair_color":"black"})
        pd.DataFrame(rows).to_csv(root/"reviews_all.csv",index=False)
        sys.argv=["smoke", "--data-dir",str(root),"--run-name","_smoke_"+uuid.uuid4().hex[:8], "--epochs","1","2",
                  "--components","8","--tree-iterations","20","--validation-users","40","--test-users","40"]
        main()


if __name__=="__main__":
    run()
