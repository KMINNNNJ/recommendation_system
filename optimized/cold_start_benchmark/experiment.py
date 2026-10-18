"""Reproducible cold-user benchmark. Run with --help; never writes raw data."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / ".packages"))
os.environ.setdefault("OMP_NUM_THREADS", "4")

import joblib
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import normalize

PROFILE = ["skin_type", "skin_tone", "eye_color", "hair_color"]
REVIEW_COLUMNS = ["author_id", "product_id", "submission_time", "rating", "is_recommended", *PROFILE]
PRODUCT_CATS = ["brand_name", "secondary_category", "tertiary_category", "variation_type"]
SEED = 42


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def clean(value):
    if pd.isna(value):
        return "unknown"
    return " ".join(str(value).strip().casefold().split()) or "unknown"


def review_fingerprint(paths):
    """Order-independent digest of complete CSV rows, excluding saved indices.

    SHA256 of sorted pandas 64-bit row hashes is an equality audit, not a
    cryptographic guarantee against deliberately constructed row collisions.
    """
    parts = []
    for path in paths:
        for chunk in pd.read_csv(path, dtype=str, keep_default_na=False, chunksize=25_000):
            columns = sorted(c for c in chunk if c and not c.startswith("Unnamed:"))
            rows = pd.util.hash_pandas_object(chunk[columns], index=False, categorize=False)
            parts.append(rows.to_numpy(dtype=np.uint64))
    values = np.concatenate(parts)
    values.sort()
    return {"rows": len(values), "row_multiset_digest": hashlib.sha256(values.tobytes()).hexdigest()}


def split_users(user_ids, seed=SEED):
    ids = np.array(sorted(set(user_ids)), dtype=object)
    np.random.default_rng(seed).shuffle(ids)
    first, second = int(len(ids) * .70), int(len(ids) * .85)
    return pd.DataFrame({"author_id": ids, "split": ["train"] * first + ["validation"] * (second-first) + ["test"] * (len(ids)-second)})


def label_reviews(frame):
    positive = frame.rating.ge(4) & (frame.is_recommended.isna() | frame.is_recommended.eq(1))
    negative = frame.rating.le(2) | frame.is_recommended.eq(0)
    # Ambiguous 3-star reviews without explicit rejection remain unlabelled.
    return pd.Series(np.select([positive, negative], [1, 0], default=-1), index=frame.index, dtype="int8")


def ingredient_tokens(value):
    if pd.isna(value):
        return []
    try:
        parsed = ast.literal_eval(str(value))
        if not isinstance(parsed, list):
            parsed = [str(value)]
    except (SyntaxError, ValueError):
        parsed = [str(value)]
    return sorted(set(clean(token) for token in ",".join(map(str, parsed)).split(",") if len(clean(token)) >= 3))


def prepare(data_dir, output, audit=True):
    products = pd.read_csv(data_dir / "product_info.csv", dtype={"product_id": str})
    if products.product_id.duplicated().any():
        raise ValueError("Duplicate product IDs in product catalogue")
    products = products.loc[products.primary_category.eq("Skincare")].sort_values("product_id").reset_index(drop=True)
    merged = sorted(data_dir.glob("reviews_all*.csv"))
    chunks = sorted(data_dir.glob("reviews_*-*.csv"))
    if len(merged) > 1:
        raise ValueError("Multiple merged review files; choose one explicitly")
    # Original Kaggle parts are authoritative when present; the user-created
    # merged copy is audited but never appended to those same review rows.
    paths = chunks or merged
    if not paths:
        raise FileNotFoundError("No review CSV files found")
    audit_result = {"chosen_sources": [str(p.resolve()) for p in paths], "never_concatenate_merged_and_parts": True,
                    "selection_rule":"prefer original Kaggle parts; otherwise use the sole merged CSV",
                    "audit_skipped":not audit}
    if merged and chunks and audit:
        log("Auditing merged review CSV against five parts")
        audit_result["merged"] = review_fingerprint(merged)
        audit_result["parts"] = review_fingerprint(chunks)
        audit_result["merged_matches_parts"] = audit_result["merged"] == audit_result["parts"]
    save_json(output / "source_audit.json", audit_result)
    frames = [pd.read_csv(p, usecols=REVIEW_COLUMNS, dtype={"author_id": str, "product_id": str}) for p in paths]
    reviews = pd.concat(frames, ignore_index=True)
    raw_count = len(reviews)
    reviews = reviews.dropna(subset=["author_id", "product_id"])
    reviews = reviews.loc[reviews.product_id.isin(products.product_id)].copy()
    reviews["rating"] = pd.to_numeric(reviews.rating, errors="coerce")
    reviews["is_recommended"] = pd.to_numeric(reviews.is_recommended, errors="coerce")
    reviews["submission_time"] = pd.to_datetime(reviews.submission_time, errors="coerce")
    invalid_rating = int((~reviews.rating.between(1, 5)).sum())
    invalid_date = int(reviews.submission_time.isna().sum())
    reviews = reviews.loc[reviews.rating.between(1, 5) & reviews.submission_time.notna()].copy()
    for column in PROFILE:
        reviews[column] = reviews[column].map(clean)
    # Freeze user input before deduplicating targets. Never aggregate future
    # profile values, review text, ratings, or target product into user features.
    reviews = reviews.sort_values("submission_time", kind="stable")
    profiles = reviews.drop_duplicates("author_id", keep="first")[["author_id", *PROFILE]].copy()
    pairs_before = len(reviews)
    reviews = reviews.drop_duplicates(["author_id", "product_id"], keep="last")
    reviews = reviews[["author_id", "product_id", "rating", "is_recommended", "submission_time"]].copy()
    splits = split_users(profiles.author_id)
    profiles = profiles.merge(splits, on="author_id", validate="one_to_one")
    # Freeze category vocabulary using training users only; unsupported values
    # become unknown for every model, not only for LightFM.
    vocabulary = {}
    for column in PROFILE:
        allowed = set(profiles.loc[profiles.split.eq("train"), column]) | {"unknown"}
        vocabulary[column] = sorted(allowed)
        profiles.loc[~profiles[column].isin(allowed), column] = "unknown"
    reviews = reviews.merge(profiles, on="author_id", validate="many_to_one")
    reviews["label"] = label_reviews(reviews)
    splits.to_csv(output / "user_splits.csv", index=False)
    products.to_pickle(output / "catalogue.pkl")
    reviews.to_pickle(output / "reviews_prepared.pkl")
    profiles.to_pickle(output / "profiles.pkl")
    summary = {
        "raw_review_rows": raw_count, "skincare_catalogue_items": len(products),
        "invalid_rating_rows": invalid_rating, "invalid_date_rows": invalid_date,
        "duplicate_user_item_rows_removed": pairs_before-len(reviews),
        "prepared_review_rows": len(reviews), "users": len(profiles),
        "users_by_split": {k: int(v) for k,v in profiles.split.value_counts().items()},
        "labels": {str(k): int(v) for k,v in reviews.label.value_counts().items()},
        "train_positive_items": int(reviews.loc[reviews.split.eq("train") & reviews.label.eq(1), "product_id"].nunique()),
        "user_feature_vocabulary": vocabulary,
        "profile_source": "first valid dated skincare review; self-reported fields only",
        "catalogue_snapshot_limitation": "Product metadata is a static snapshot; no historical ingredient/price snapshots available.",
        "evaluation_limitation": "Reviewers are a selected population; ranking positive reviews is an offline proxy, not a purchase/efficacy test.",
    }
    save_json(output / "data_summary.json", summary)
    log(f"Prepared {len(reviews):,} reviews / {len(profiles):,} users / {len(products):,} items")
    return products, reviews, profiles


class Features:
    def __init__(self, products, train_profiles):
        self.products = products
        self.item_map = {pid: i for i,pid in enumerate(products.product_id)}
        self.product_rows = []
        ingredients = products.ingredients.map(ingredient_tokens)
        counts = Counter(token for tokens in ingredients for token in tokens)
        self.ingredient_names = [token for token,count in counts.most_common(80) if count >= 10]
        self.tree_products = pd.DataFrame(index=products.index)
        for col in PRODUCT_CATS:
            self.tree_products[col] = products[col].map(clean)
        prices = pd.to_numeric(products.price_usd, errors="coerce").clip(lower=0)
        # An unknown price is a separate feature, not the test-set mean.
        self.tree_products["price_missing"] = prices.isna().astype("int8")
        self.tree_products["log_price"] = np.log1p(prices.fillna(0)).astype("float32")
        for index, token in enumerate(self.ingredient_names):
            self.tree_products[f"ingredient_{index}"] = ingredients.map(lambda values: int(token in values)).astype("int8")
        for i,row in products.iterrows():
            values = {f"{col}={clean(row[col])}": 1.0 for col in PRODUCT_CATS}
            values[f"price_band={int(np.searchsorted([15,30,50,80], prices.iloc[i])) if pd.notna(prices.iloc[i]) else 'unknown'}"] = 1.0
            kept = [token for token in ingredients.iloc[i] if counts[token] >= 5]
            # Ingredient group has constant total weight regardless of length.
            for token in kept:
                values[f"ingredient={token}"] = 1.0 / len(kept)
            self.product_rows.append(values)
        self.item_vectorizer = DictVectorizer(dtype=np.float32)
        side = self.item_vectorizer.fit_transform(self.product_rows)
        self.item_matrix = normalize(sparse.hstack([sparse.eye(len(products), dtype=np.float32), side], format="csr"), norm="l1").tocsr()
        self.user_vectorizer = DictVectorizer(dtype=np.float32)
        dictionaries = self.profile_dicts(train_profiles, PROFILE)
        # Ensure an unknown feature exists even when training data is complete.
        self.user_vectorizer.fit(dictionaries + [{f"{col}=unknown": 1.0 for col in PROFILE}])
        self.skin_vectorizer = DictVectorizer(dtype=np.float32)
        self.skin_vectorizer.fit(self.profile_dicts(train_profiles, ["skin_type"]) + [{"skin_type=unknown": 1.0}])

    @staticmethod
    def profile_dicts(frame, columns):
        return [{f"{col}={value}": 1.0 for col,value in zip(columns, row)} for row in frame[columns].itertuples(index=False, name=None)]

    def user_matrix(self, profiles, skin_only=False):
        vectorizer = self.skin_vectorizer if skin_only else self.user_vectorizer
        cols = ["skin_type"] if skin_only else PROFILE
        return normalize(vectorizer.transform(self.profile_dicts(profiles, cols)), norm="l1").tocsr()

    def tree_pairs(self, frame):
        indices = frame.product_id.map(self.item_map).to_numpy()
        result = self.tree_products.iloc[indices].reset_index(drop=True).copy()
        for col in PROFILE:
            result[col] = frame[col].to_numpy()
        return result

    def tree_candidates(self, profiles):
        count = len(self.products)
        result = pd.concat([self.tree_products] * len(profiles), ignore_index=True)
        for col in PROFILE:
            result[col] = np.repeat(profiles[col].to_numpy(), count)
        return result


class Evaluation:
    def __init__(self, reviews, split, products, max_users, seed=SEED):
        section = reviews.loc[reviews.split.eq(split)]
        users = np.array(sorted(section.loc[section.label.eq(1), "author_id"].unique()), dtype=object)
        self.eligible_users = len(users)
        if max_users and len(users) > max_users:
            users = np.random.default_rng(seed).choice(users, max_users, replace=False)
        section = section.loc[section.author_id.isin(users)]
        self.users = section.drop_duplicates("author_id").set_index("author_id").loc[users, PROFILE].reset_index()
        self.unique_profiles = self.users[PROFILE].drop_duplicates().reset_index(drop=True)
        key_map = {row:i for i,row in enumerate(self.unique_profiles.itertuples(index=False, name=None))}
        self.profile_index = np.array([key_map[row] for row in self.users[PROFILE].itertuples(index=False, name=None)])
        item_map = {pid:i for i,pid in enumerate(products.product_id)}
        self.positive = section.loc[section.label.eq(1)].groupby("author_id").product_id.agg(lambda x: set(x.map(item_map)))
        self.negative = section.loc[section.label.eq(0)].groupby("author_id").product_id.agg(lambda x: set(x.map(item_map)))

    def evaluate(self, scores, k=10):
        scores = np.asarray(scores)
        if scores.shape[0] != len(self.unique_profiles) or not np.isfinite(scores).all():
            raise ValueError("Invalid ranking score matrix")
        # Stable tie-breaking by sorted product_id, identical across models.
        top = np.argsort(-scores, axis=1, kind="stable")[:, :k]
        rows = []
        for uid,profile in zip(self.users.author_id, self.profile_index):
            truth = self.positive[uid]
            negative = self.negative.get(uid, set())
            hits = np.array([int(item in truth) for item in top[profile]])
            dcg = float(np.sum(hits / np.log2(np.arange(k)+2)))
            idcg = float(np.sum(1 / np.log2(np.arange(min(len(truth),k))+2)))
            rows.append((uid, float(hits.sum()/k), float(hits.sum()/len(truth)), dcg/idcg,
                         int(hits.any()), sum(item in negative for item in top[profile])/k))
        detail = pd.DataFrame(rows, columns=["author_id", "precision@10", "recall@10", "ndcg@10", "hit_rate@10", "known_negative@10"])
        metrics = {c:float(detail[c].mean()) for c in detail.columns[1:]}
        metrics.update(evaluated_users=len(detail), unique_profiles=len(self.unique_profiles),
                       eligible_users=self.eligible_users, catalogue_coverage_at_10=float(len(np.unique(top[self.profile_index]))/scores.shape[1]))
        return metrics, detail, top


def baseline_scores(train, features, profiles, cohort=False, strength=20, popularity=False):
    if popularity:
        counts=train.loc[train.label.eq(1),"product_id"].value_counts().reindex(features.products.product_id,fill_value=0)
        return np.tile(counts.to_numpy(dtype=np.float32),(len(profiles),1))
    labelled = train.loc[train.label.ge(0)]
    prior = float(labelled.label.mean())
    global_stats = labelled.groupby("product_id").label.agg(["sum", "count"]).reindex(features.products.product_id, fill_value=0)
    global_score = (global_stats["sum"].to_numpy()+strength*prior)/(global_stats["count"].to_numpy()+strength)
    if not cohort:
        return np.tile(global_score, (len(profiles),1))
    by_skin = {}
    for skin in profiles.skin_type.unique():
        stats = labelled.loc[labelled.skin_type.eq(skin)].groupby("product_id").label.agg(["sum", "count"]).reindex(features.products.product_id, fill_value=0)
        by_skin[skin] = (stats["sum"].to_numpy()+strength*global_score)/(stats["count"].to_numpy()+strength)
    return np.asarray([by_skin[skin] for skin in profiles.skin_type])


def lightfm_scores(model, features, profiles, identity_count=0, skin_only=False):
    matrix = features.user_matrix(profiles, skin_only)
    if identity_count:
        matrix = sparse.hstack([sparse.csr_matrix((len(profiles), identity_count), dtype=np.float32), matrix], format="csr")
    biases, users = model.get_user_representations(matrix)
    item_biases, items = model.get_item_representations(features.item_matrix)
    return users @ items.T + biases[:,None] + item_biases[None,:]


def tree_scores(model, features, profiles, catboost=False):
    matrices = []
    for start in range(0, len(profiles), 12):
        frame = features.tree_candidates(profiles.iloc[start:start+12])
        if not catboost:
            for col in PRODUCT_CATS + PROFILE:
                frame[col] = pd.Categorical(frame[col], categories=model._benchmark_categories[col])
        prediction = model.predict_proba(frame)[:,1]
        matrices.append(prediction.reshape(-1,len(features.products)))
    return np.vstack(matrices)


def run(args):
    output = HERE / "artifacts" / args.run_name
    output.mkdir(parents=True, exist_ok=True)
    if (output / "comparison.json").exists():
        raise FileExistsError("This run already completed; choose a different --run-name")
    if args.prepared_from:
        previous_config=json.loads((args.prepared_from/"config.json").read_text(encoding="utf-8"))
        if Path(previous_config["data_dir"]).resolve()!=args.data_dir.resolve():
            raise ValueError("Prepared cache belongs to a different data directory")
        for name in ["source_audit.json","data_summary.json","user_splits.csv","catalogue.pkl","reviews_prepared.pkl","profiles.pkl"]:
            shutil.copy2(args.prepared_from/name,output/name)
        products=pd.read_pickle(output/"catalogue.pkl")
        reviews=pd.read_pickle(output/"reviews_prepared.pkl")
        profiles=pd.read_pickle(output/"profiles.pkl")
        log(f"Reused audited, frozen split: {len(reviews):,} reviews")
    else:
        products, reviews, profiles = prepare(args.data_dir, output, not args.skip_source_audit)
    train = reviews.loc[reviews.split.eq("train")].copy()
    train_profiles = profiles.loc[profiles.split.eq("train")].reset_index(drop=True)
    features = Features(products, train_profiles)
    validation = Evaluation(reviews, "validation", products, args.validation_users)
    test = Evaluation(reviews, "test", products, args.test_users)
    validation.users.to_csv(output / "validation_users.csv", index=False)
    test.users.to_csv(output / "test_users.csv", index=False)
    joblib.dump(features, output / "features.joblib", compress=3)
    import lightfm._lightfm_fast as native
    native_path=Path(importlib.import_module(native.fit_warp.__module__).__file__)
    if args.lightfm_threads>1 and "no_openmp" in native.fit_warp.__module__:
        raise RuntimeError("This LightFM build lacks OpenMP; use --lightfm-threads 1")
    save_json(output / "config.json", {**vars(args), "data_dir":str(args.data_dir.resolve()),
              "prepared_from":str(args.prepared_from.resolve()) if args.prepared_from else None,
              "python":platform.python_version(),
              "seed":SEED, "selection_metric":"validation ndcg@10 for LightFM; validation logloss for tree early stopping",
              "test_used_for_model_selection":False, "candidate_pool":"all skincare catalogue items, fixed across users and models",
              "objective_difference":"WARP uses positive reviews; tree classifiers use observed positive/negative reviews. End-to-end approaches, not loss-controlled ablations.",
              "lightfm_threads":args.lightfm_threads,
              "lightfm_native_module":native.fit_warp.__module__,
              "lightfm_distribution":importlib.metadata.version("lightfm-next"),
              "lightfm_windows_private_fix":"unsigned rand_r conversion: (uint32 temper(seed) >> 1), rebuilt by build_windows_lightfm.py",
              "lightfm_extension_sha256":hashlib.sha256(native_path.read_bytes()).hexdigest(),
              "package_versions":{name:__import__(name).__version__ for name in ["numpy","pandas","scipy","sklearn","catboost","lightgbm"]}})
    results = []
    validation_history = []
    # All hyperparameter/checkpoint selection happens before any test scoring.
    predictors = []
    for name,cohort in [("global_popularity",False),("global_bayesian",False),("skin_type_bayesian",True)]:
        best = (-1,None)
        for strength in ([0] if name=="global_popularity" else [10,50,100]):
            scores = baseline_scores(train,features,validation.unique_profiles,cohort,strength,popularity=name=="global_popularity")
            metric = validation.evaluate(scores)[0]["ndcg@10"]
            validation_history.append({"model":name,"strength":strength,"ndcg@10":metric})
            if metric > best[0]: best=(metric,strength)
        predictors.append((name,{"kind":"baseline","cohort":cohort,"strength":best[1],"popularity":name=="global_popularity"},best[0],0.0))
        log(f"{name}: validation NDCG@10={best[0]:.6f}")
    from lightfm import LightFM
    train_user_map = {uid:i for i,uid in enumerate(train_profiles.author_id)}
    positive = train.loc[train.label.eq(1)]
    interactions = sparse.coo_matrix((np.ones(len(positive),dtype=np.float32),
        (positive.author_id.map(train_user_map),positive.product_id.map(features.item_map))),shape=(len(train_profiles),len(products)))
    for name,skin_only,identity in [("lightfm_profile",False,False),("lightfm_skin_only",True,False),("lightfm_identity_ablation",False,True)]:
        log(f"Training {name} on {interactions.nnz:,} positives")
        start = time.perf_counter()
        user_matrix = features.user_matrix(train_profiles,skin_only)
        identity_count = len(train_profiles) if identity else 0
        if identity:
            user_matrix = normalize(sparse.hstack([sparse.eye(identity_count,dtype=np.float32),user_matrix*len(PROFILE)],format="csr"),norm="l1").tocsr()
        model = LightFM(loss="warp",no_components=args.components,learning_rate=.05,user_alpha=1e-5,item_alpha=1e-5,max_sampled=10,random_state=SEED)
        best = -1.0
        previous = 0
        for epoch in args.epochs:
            model.fit_partial(interactions,user_features=user_matrix,item_features=features.item_matrix,epochs=epoch-previous,num_threads=args.lightfm_threads)
            previous=epoch
            scores = lightfm_scores(model,features,validation.unique_profiles,identity_count,skin_only)
            metric = validation.evaluate(scores)[0]["ndcg@10"]
            validation_history.append({"model":name,"epochs":epoch,"ndcg@10":metric})
            log(f"{name} epoch {epoch}: validation NDCG@10={metric:.6f}")
            if metric > best:
                best=metric
                joblib.dump({"model":model,"identity_count":identity_count,"skin_only":skin_only,"epoch":epoch},output/f"{name}.joblib",compress=3)
        predictors.append((name,{"kind":"lightfm","path":str(output/f"{name}.joblib")},best,time.perf_counter()-start))
        del model,user_matrix
    labelled = train.loc[train.label.ge(0)]
    valid_labels = reviews.loc[reviews.split.eq("validation") & reviews.label.ge(0)]
    X_train = features.tree_pairs(labelled)
    X_valid = features.tree_pairs(valid_labels)
    y_train,y_valid = labelled.label.to_numpy(),valid_labels.label.to_numpy()
    cat_columns=PRODUCT_CATS+PROFILE
    from catboost import CatBoostClassifier
    start=time.perf_counter()
    log(f"Training CatBoost on {len(labelled):,} observed labelled reviews")
    model=CatBoostClassifier(iterations=args.tree_iterations,depth=6,learning_rate=.05,loss_function="Logloss",eval_metric="Logloss",random_seed=SEED,thread_count=args.threads,allow_writing_files=False)
    model.fit(X_train,y_train,cat_features=cat_columns,eval_set=(X_valid,y_valid),early_stopping_rounds=40,verbose=100)
    metric=validation.evaluate(tree_scores(model,features,validation.unique_profiles,True))[0]["ndcg@10"]
    model.save_model(str(output/"catboost.cbm"))
    predictors.append(("catboost",{"kind":"catboost","path":str(output/"catboost.cbm")},metric,time.perf_counter()-start))
    validation_history.append({"model":"catboost","best_iteration":int(model.best_iteration_),"ndcg@10":metric})
    del model
    from lightgbm import LGBMClassifier,early_stopping,log_evaluation
    log("Training LightGBM classifier (observed positive/negative reviews)")
    categories={col:sorted(set(X_train[col])|{"unknown"}) for col in cat_columns}
    for col in cat_columns:
        X_train[col]=pd.Categorical(X_train[col],categories=categories[col])
        X_valid[col]=pd.Categorical(X_valid[col],categories=categories[col])
    start=time.perf_counter()
    model=LGBMClassifier(n_estimators=args.tree_iterations,num_leaves=31,learning_rate=.05,reg_lambda=5,min_child_samples=100,random_state=SEED,n_jobs=args.threads,verbosity=-1)
    model.fit(X_train,y_train,eval_set=[(X_valid,y_valid)],eval_metric="binary_logloss",callbacks=[early_stopping(40),log_evaluation(100)])
    model._benchmark_categories=categories
    metric=validation.evaluate(tree_scores(model,features,validation.unique_profiles))[0]["ndcg@10"]
    joblib.dump(model,output/"lightgbm.joblib",compress=3)
    predictors.append(("lightgbm",{"kind":"lightgbm","path":str(output/"lightgbm.joblib")},metric,time.perf_counter()-start))
    validation_history.append({"model":"lightgbm","best_iteration":int(model.best_iteration_),"ndcg@10":metric})
    del model,X_train,X_valid
    save_json(output/"validation_history.json",validation_history)
    selected_name=max(predictors,key=lambda p:p[2])[0]
    log(f"Selected using validation only: {selected_name}; beginning final test evaluation")
    for name,spec,val_metric,train_seconds in predictors:
        start=time.perf_counter()
        if spec["kind"]=="baseline":
            scores=baseline_scores(train,features,test.unique_profiles,spec["cohort"],spec["strength"],spec.get("popularity",False))
        elif spec["kind"]=="lightfm":
            bundle=joblib.load(spec["path"])
            scores=lightfm_scores(bundle["model"],features,test.unique_profiles,bundle["identity_count"],bundle["skin_only"])
        elif spec["kind"]=="catboost":
            model=CatBoostClassifier();model.load_model(spec["path"])
            scores=tree_scores(model,features,test.unique_profiles,True)
        else:
            scores=tree_scores(joblib.load(spec["path"]),features,test.unique_profiles)
        metrics,detail,top=test.evaluate(scores)
        detail=detail.merge(test.users[["author_id","skin_type"]],on="author_id",validate="one_to_one")
        detail.to_csv(output/f"{name}_per_user.csv",index=False)
        detail.groupby("skin_type")[list(metrics.keys())[:5]].mean().to_csv(output/f"{name}_by_skin.csv")
        np.save(output/f"{name}_top10_by_profile.npy",top)
        result={"model":name,"validation_ndcg@10":val_metric,"selected_by_validation":name==selected_name,"training_seconds":train_seconds,"test_scoring_seconds":time.perf_counter()-start,**metrics}
        results.append(result)
        save_json(output/"comparison.json",results)
        pd.DataFrame(results).to_csv(output/"comparison.csv",index=False)
        log(f"{name}: TEST Recall@10={metrics['recall@10']:.6f} NDCG@10={metrics['ndcg@10']:.6f}")
    # Summarize paired uncertainty against the validation-selected model.
    selected=pd.read_csv(output/f"{selected_name}_per_user.csv",dtype={"author_id":str}).set_index("author_id")
    comparisons=[]
    for result in results:
        other=pd.read_csv(output/f"{result['model']}_per_user.csv",dtype={"author_id":str}).set_index("author_id").reindex(selected.index)
        difference=(selected["ndcg@10"]-other["ndcg@10"]).to_numpy()
        rng=np.random.default_rng(SEED)
        bootstrap=np.array([rng.choice(difference,len(difference),replace=True).mean() for _ in range(500)])
        comparisons.append({"selected":selected_name,"against":result["model"],"ndcg_difference":float(difference.mean()),"paired_bootstrap_95ci":[float(x) for x in np.quantile(bootstrap,[.025,.975])]})
    save_json(output/"paired_uncertainty.json",comparisons)
    save_json(output/"selected_model.json",{"model":selected_name,"spec":next(p[1] for p in predictors if p[0]==selected_name),"selected_using":"validation NDCG@10","deployment_status":"offline experiment only; production API unchanged"})
    log(f"Complete. Results: {output}")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",type=Path,default=HERE.parents[1]/"data/raw/cosmetics")
    parser.add_argument("--run-name",default="cold_users_v2")
    parser.add_argument("--validation-users",type=int,default=3000)
    parser.add_argument("--test-users",type=int,default=10000)
    parser.add_argument("--epochs",type=int,nargs="+",default=[5,15,30])
    parser.add_argument("--components",type=int,default=32)
    parser.add_argument("--tree-iterations",type=int,default=500)
    parser.add_argument("--threads",type=int,default=4)
    parser.add_argument("--lightfm-threads",type=int,default=1)
    parser.add_argument("--prepared-from",type=Path)
    parser.add_argument("--skip-source-audit",action="store_true")
    args=parser.parse_args()
    if args.epochs!=sorted(set(args.epochs)) or min(args.epochs)<1:
        parser.error("--epochs must be positive and strictly increasing")
    if args.validation_users<0 or args.test_users<0 or args.components<1 or args.tree_iterations<1 or args.threads<1 or args.lightfm_threads<1:
        parser.error("Invalid evaluation/training sizes")
    if Path(args.run_name).name!=args.run_name or args.run_name in (".",".."):
        parser.error("--run-name must be a single directory name")
    run(args)


if __name__=="__main__":
    main()
