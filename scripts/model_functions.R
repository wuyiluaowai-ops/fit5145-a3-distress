# Modelling helpers for report/A3_demo.Rmd
# Laitinen (1993) trajectory features + MD&A tone features, grouped CV by pair_id.
suppressPackageStartupMessages({
  library(dplyr); library(tidyr); library(purrr)
  library(glmnet); library(xgboost); library(pROC); library(rsample)
})

# Ratios used for Laitinen features; "up" = higher is healthier, "down" = higher is worse
LAITINEN_RATIOS <- c(
  roa = "up", gpMargin = "up", cfo_to_assets = "up", AssetTurnRatio = "up",
  currentRatio = "up", cashRatio = "up", liabilityToAsset = "down"
)
TONE_VARS <- "net_tone"
# extension text variables: winsorised, and (for TEXT_ADJ_VARS) demeaned by fiscal year -> *_adj
TEXT_VARS <- c("net_tone", "neg_ratio", "ln_words", "outlook_tone", "audit_tone", "ln_audit_words")
TEXT_ADJ_VARS <- c("net_tone", "neg_ratio", "outlook_tone")
FEATURE_WINDOW <- -6:-2   # rel_year -1 is never used (leakage guard)

# ---------------------------------------------------------------- data prep
winsorize <- function(x, p = c(0.01, 0.99)) {
  q <- quantile(x, p, na.rm = TRUE, names = FALSE)
  pmin(pmax(x, q[1]), q[2])
}

load_panel <- function(data_dir, tone_file = "tone.csv") {
  rd <- function(f) readr::read_csv(file.path(data_dir, f),
                                    col_types = readr::cols(code = "c", .default = "?"), show_col_types = FALSE)
  tone <- rd(tone_file) %>% select(code, fiscal_year, n_words, n_neg, net_tone) %>%
    mutate(neg_ratio = n_neg / n_words, ln_words = log(n_words))
  panel <- rd("ratios.csv") %>% left_join(tone, by = c("code", "fiscal_year"))
  # extension inputs (Section 9); optional so the core analysis runs without them
  for (f in c("tone_outlook.csv", "disclosure_flags.csv", "audit_features.csv")) {
    if (file.exists(file.path(data_dir, f))) panel <- left_join(panel, rd(f), by = c("code", "fiscal_year"))
  }
  for (v in c("outlook_tone", "audit_nonstd", "audit_modified", "audit_emphasis", "going_concern", "ic_adverse",
              "audit_tone", "audit_words", "kam_count", "proc_n"))
    if (!v %in% names(panel)) panel[[v]] <- NA_real_
  panel %>% mutate(y = as.integer(group == "distress"),
                   flagged = toupper(as.character(flagged)) == "TRUE",
                   ln_audit_words = ifelse(audit_words > 0, log(audit_words), NA_real_),
                   ln_proc = ifelse(is.na(proc_n), NA_real_, log1p(proc_n)),
                   # ordinal opinion severity: 0 standard, 1 emphasis of matter, 2 going-concern section,
                   # 3 modified opinion or adverse internal-control opinion
                   severity = ifelse(is.na(audit_nonstd), NA_real_,
                                     pmax(3 * (audit_modified == 1 | ic_adverse == 1), 2 * (going_concern == 1),
                                          1 * (audit_emphasis == 1), 0, na.rm = TRUE)))
}

# express the ratios relative to their fiscal-year benchmark across the sample (industry-year
# adjustment; every fiscal-year group is 1:2 distress:control by design, so no label information
# enters). method: "diff" = ratio - year mean (used in the report), "z" = (ratio - mean) / sd,
# "ratio" = ratio / year mean (Platt & Platt 1990), "ratio_median" = ratio / year median.
# The ratio forms are re-winsorised because year means of ROA are close to zero in several years.
industry_adjusted <- function(panel, vars = names(LAITINEN_RATIOS), method = "diff") {
  f <- switch(method,
    diff         = function(x) x - mean(x, na.rm = TRUE),
    z            = function(x) (x - mean(x, na.rm = TRUE)) / sd(x, na.rm = TRUE),
    ratio        = function(x) x / mean(x, na.rm = TRUE),
    ratio_median = function(x) x / median(x, na.rm = TRUE),
    stop("unknown method"))
  out <- panel %>% group_by(fiscal_year) %>% mutate(across(all_of(vars), f)) %>% ungroup() %>%
    mutate(across(all_of(vars), ~ ifelse(is.finite(.x), .x, NA_real_)))
  if (method %in% c("ratio", "ratio_median")) out <- winsorize_panel(out, vars)
  out
}

winsorize_panel <- function(panel, vars) {
  mutate(panel, across(all_of(vars), winsorize))
}

# subtract the fiscal-year mean across all sample firms (industry-year adjustment; uses X only)
adjust_by_year <- function(panel, vars = TEXT_ADJ_VARS) {
  panel %>% group_by(fiscal_year) %>%
    mutate(across(all_of(vars), ~ .x - mean(.x, na.rm = TRUE), .names = "{.col}_adj")) %>%
    ungroup()
}

# ---------------------------------------------------------------- features
ols_slope <- function(y, x) {
  ok <- !is.na(y)
  if (sum(ok) < 3) return(NA_real_)
  unname(coef(lm(y[ok] ~ x[ok]))[2])
}
val_at <- function(y, x, t) {
  v <- y[x == t]
  if (length(v)) v[1] else NA_real_
}
# largest single-year deterioration (positive = worse), direction-aware
max_deterioration <- function(y, x, direction) {
  y <- y[order(x)]
  d <- diff(y)
  if (all(is.na(d))) return(NA_real_)
  if (direction == "up") max(-d, na.rm = TRUE) else max(d, na.rm = TRUE)
}

build_features <- function(panel, window = FEATURE_WINDOW, lvl = max(window)) {
  # lvl = year of the level features; changes are lvl vs lvl-1; early change = first two window years
  L <- lvl; P <- lvl - 1; E0 <- min(window); E1 <- E0 + 1
  w <- filter(panel, rel_year %in% window)
  firm <- w %>% distinct(code, name, group, pair_id, flagged, y)

  lait <- map(names(LAITINEN_RATIOS), function(r) {
    dir <- LAITINEN_RATIOS[[r]]
    w %>% group_by(code) %>%
      summarise(
        "{r}_lvl"   := val_at(.data[[r]], rel_year, L),
        "{r}_slope" := ols_slope(.data[[r]], rel_year),
        "{r}_d65"   := val_at(.data[[r]], rel_year, E1) - val_at(.data[[r]], rel_year, E0),
        "{r}_maxdet" := max_deterioration(.data[[r]], rel_year, dir),
        .groups = "drop")
  }) %>% reduce(left_join, by = "code")

  size <- w %>% group_by(code) %>%
    summarise(ln_assets_lvl = val_at(ln_total_assets, rel_year, L), .groups = "drop")

  tone <- w %>% group_by(code) %>%
    summarise(
      tone_lvl   = val_at(net_tone, rel_year, L),
      tone_chg   = val_at(net_tone, rel_year, L) - val_at(net_tone, rel_year, P),
      tone_slope = ols_slope(net_tone, rel_year),
      .groups = "drop")

  # extension: year-adjusted tone, negative-word share, report length, outlook tone, audit flags
  any_flag <- function(v) if (all(is.na(v))) NA_integer_ else as.integer(any(v == 1, na.rm = TRUE))
  text2 <- w %>% group_by(code) %>%
    summarise(
      tone_adj_lvl    = val_at(net_tone_adj, rel_year, L),
      tone_adj_chg    = val_at(net_tone_adj, rel_year, L) - val_at(net_tone_adj, rel_year, P),
      tone_adj_slope  = ols_slope(net_tone_adj, rel_year),
      negr_adj_lvl    = val_at(neg_ratio_adj, rel_year, L),
      negr_adj_chg    = val_at(neg_ratio_adj, rel_year, L) - val_at(neg_ratio_adj, rel_year, P),
      ln_words_lvl    = val_at(ln_words, rel_year, L),
      ln_words_chg    = val_at(ln_words, rel_year, L) - val_at(ln_words, rel_year, P),
      outlook_adj_lvl = val_at(outlook_tone_adj, rel_year, L),
      outlook_adj_chg = val_at(outlook_tone_adj, rel_year, L) - val_at(outlook_tone_adj, rel_year, P),
      audit_nonstd_lvl = val_at(audit_nonstd, rel_year, L),
      audit_nonstd_any = any_flag(audit_nonstd),
      .groups = "drop")

  # auditor's report: lexicon tone, length, key-audit-matter count
  aud <- w %>% group_by(code) %>%
    summarise(
      audit_tone_lvl     = val_at(audit_tone, rel_year, L),
      audit_tone_chg     = val_at(audit_tone, rel_year, L) - val_at(audit_tone, rel_year, P),
      ln_audit_words_lvl = val_at(ln_audit_words, rel_year, L),
      kam_lvl            = val_at(kam_count, rel_year, L),
      kam_chg            = val_at(kam_count, rel_year, L) - val_at(kam_count, rel_year, P),
      sev_lvl            = val_at(severity, rel_year, L),
      sev_max            = if (all(is.na(severity))) NA_real_ else max(severity, na.rm = TRUE),
      proc_lvl           = val_at(ln_proc, rel_year, L),
      proc_chg           = val_at(ln_proc, rel_year, L) - val_at(ln_proc, rel_year, P),
      .groups = "drop")

  firm %>% left_join(lait, by = "code") %>% left_join(size, by = "code") %>%
    left_join(tone, by = "code") %>% left_join(text2, by = "code") %>% left_join(aud, by = "code") %>%
    mutate(across(where(is.numeric), ~ ifelse(is.finite(.x), .x, NA_real_)))
}

laitinen_features <- function(feat) {
  c(grep(paste0("^(", paste(names(LAITINEN_RATIOS), collapse = "|"), ")_"), names(feat), value = TRUE),
    "ln_assets_lvl")
}
tone_features <- function() c("tone_lvl", "tone_chg", "tone_slope")
refined_text_features <- function() c("tone_adj_lvl", "tone_adj_chg", "tone_adj_slope",
                                      "negr_adj_lvl", "negr_adj_chg", "ln_words_lvl", "ln_words_chg",
                                      "outlook_adj_lvl", "outlook_adj_chg")
disclosure_features <- function() c("audit_nonstd_lvl", "audit_nonstd_any")
audit_tone_features <- function() c("audit_tone_lvl", "audit_tone_chg")
kam_features <- function() c("kam_lvl", "kam_chg", "ln_audit_words_lvl")
audit_severity_features <- function() c("sev_lvl", "sev_max")
audit_procedure_features <- function() c("proc_lvl", "proc_chg")

# ---------------------------------------------------------------- models
class_weights <- function(y) ifelse(y == 1, 2, 1)   # balances the 1:2 design

impute_median <- function(train, test) {
  med <- vapply(train, function(v) { m <- median(v, na.rm = TRUE); if (is.na(m)) 0 else m }, 0)
  fill <- function(df) { for (j in names(df)) df[[j]][is.na(df[[j]])] <- med[[j]]; as.matrix(df) }
  list(train = fill(train), test = fill(test))
}

# pair-grouped fold ids for the inner CV of cv.glmnet
pair_foldid <- function(pair_id, k) {
  pairs <- unique(pair_id)
  f <- sample(rep_len(seq_len(k), length(pairs)))
  f[match(pair_id, pairs)]
}

fit_glmnet <- function(x, y, pair_id, alphas = c(0, 0.25, 0.5, 0.75, 1), inner_k = 4) {
  foldid <- pair_foldid(pair_id, min(inner_k, length(unique(pair_id))))
  fits <- map(alphas, ~ cv.glmnet(x, y, family = "binomial", weights = class_weights(y),
                                  alpha = .x, foldid = foldid, type.measure = "deviance"))
  best <- which.min(map_dbl(fits, ~ min(.x$cvm)))
  list(fit = fits[[best]], alpha = alphas[best])
}

fit_xgb <- function(x, y) {
  d <- xgb.DMatrix(x, label = y, weight = class_weights(y))
  xgb.train(params = list(objective = "binary:logistic", eval_metric = "logloss",
                          max_depth = 2, eta = 0.05, subsample = 0.8, colsample_bytree = 0.8,
                          min_child_weight = 1, nthread = 1),
            data = d, nrounds = 150, verbose = 0)
}

# One repeat of pair-grouped 5-fold CV; both feature sets share the same folds.
run_cv_repeat <- function(feat, feature_sets, seed, v = 5) {
  set.seed(seed)
  folds <- group_vfold_cv(feat, group = pair_id, v = v)
  map_dfr(seq_along(folds$splits), function(k) {
    sp <- folds$splits[[k]]
    tr <- analysis(sp); te <- assessment(sp)
    map_dfr(names(feature_sets), function(fs) {
      cols <- feature_sets[[fs]]
      imp <- impute_median(tr[cols], te[cols])
      set.seed(seed * 1000 + k)   # inner CV folds / subsampling depend only on (repeat, fold)
      g <- fit_glmnet(imp$train, tr$y, tr$pair_id)
      p_glm <- as.numeric(predict(g$fit, imp$test, s = "lambda.min", type = "response"))
      xg <- fit_xgb(as.matrix(tr[cols]), tr$y)
      p_xgb <- predict(xg, xgb.DMatrix(as.matrix(te[cols])))
      bind_rows(
        tibble(code = te$code, y = te$y, model = fs, algo = "glmnet", p = p_glm, alpha = g$alpha),
        tibble(code = te$code, y = te$y, model = fs, algo = "xgboost", p = p_xgb, alpha = NA_real_)
      ) %>% mutate(fold = k)
    })
  }) %>% mutate(rep = seed)
}

run_cv <- function(feat, feature_sets, repeats = 5, v = 5) {
  map_dfr(seq_len(repeats), ~ run_cv_repeat(feat, feature_sets, seed = .x, v = v))
}

# ---------------------------------------------------------------- evaluation
# classification threshold for recall: set once via options(nev.threshold = ...) in the report
metrics <- function(y, p, threshold = getOption("nev.threshold", 0.5)) {
  tibble(auc = as.numeric(auc(roc(y, p, levels = c(0, 1), direction = "<", quiet = TRUE))),
         recall = mean(p[y == 1] >= threshold),
         brier = mean((p - y)^2))
}

summarise_cv <- function(oof) {
  oof %>% group_by(algo, model, rep) %>%
    summarise(metrics(y, p), .groups = "drop") %>%
    group_by(algo, model) %>%
    summarise(across(c(auc, recall, brier), list(mean = mean, sd = sd)), .groups = "drop")
}

mean_oof <- function(oof) {
  oof %>% group_by(algo, model, code, y) %>% summarise(p = mean(p), .groups = "drop")
}

delong_tests <- function(oof_mean, m1, m2) {
  oof_mean %>% group_by(algo) %>% group_modify(function(d, key) {
    a <- filter(d, model == m1); b <- filter(d, model == m2) %>% slice(match(a$code, code))
    r1 <- roc(a$y, a$p, levels = c(0, 1), direction = "<", quiet = TRUE)
    r2 <- roc(b$y, b$p, levels = c(0, 1), direction = "<", quiet = TRUE)
    t <- roc.test(r1, r2, method = "delong", paired = TRUE)
    tibble(auc_1 = as.numeric(auc(r1)), auc_2 = as.numeric(auc(r2)),
           z = unname(t$statistic), p_value = t$p.value)
  }) %>% ungroup()
}

# ---------------------------------------------------------------- temporal hold-out
# Train on the earlier event cohorts, test on the cohorts in test_T. Industry-year means,
# imputation medians and hyper-parameters all come from the training firms only.
# feature_sets may reference "<ratio>_lvl_adj" columns (training-mean-adjusted levels).
temporal_holdout <- function(panel, test_T, feature_sets, seed = 1) {
  rv <- names(LAITINEN_RATIOS)
  key <- c("code", "name", "group", "pair_id", "flagged", "y")
  is_test <- panel$event_year %in% test_T
  ym <- panel[!is_test, ] %>% group_by(fiscal_year) %>%
    summarise(across(all_of(rv), ~ mean(.x, na.rm = TRUE)), .groups = "drop")
  padj <- panel
  for (v in rv) padj[[v]] <- padj[[v]] - ym[[v]][match(padj$fiscal_year, ym$fiscal_year)]
  feat <- build_features(panel) %>%
    left_join(build_features(padj) %>% select(all_of(key), all_of(paste0(rv, "_lvl"))) %>%
                rename_with(~ paste0(.x, "_adj"), -all_of(key)), by = key)
  test_codes <- unique(panel$code[is_test])
  tr <- feat[!feat$code %in% test_codes, ]; te <- feat[feat$code %in% test_codes, ]
  preds <- imap_dfr(feature_sets, function(cols, nm) {
    imp <- impute_median(tr[cols], te[cols])
    set.seed(seed); g <- fit_glmnet(imp$train, tr$y, tr$pair_id, inner_k = 5)
    set.seed(seed); xg <- fit_xgb(as.matrix(tr[cols]), tr$y)
    bind_rows(
      tibble(model = nm, algo = "glmnet", code = te$code, name = te$name, y = te$y,
             p = as.numeric(predict(g$fit, imp$test, s = "lambda.min", type = "response"))),
      tibble(model = nm, algo = "xgboost", code = te$code, name = te$name, y = te$y,
             p = predict(xg, xgb.DMatrix(as.matrix(te[cols])))))
  })
  list(n_train = nrow(tr), n_train_distress = sum(tr$y), n_test = nrow(te), n_test_distress = sum(te$y),
       preds = preds,
       metrics = preds %>% group_by(algo, model) %>% summarise(metrics(y, p), .groups = "drop"))
}

# ---------------------------------------------------------------- interpretation
fit_full_glmnet <- function(feat, cols, seed = 1) {
  set.seed(seed)
  imp <- impute_median(feat[cols], feat[cols])
  g <- fit_glmnet(imp$train, feat$y, feat$pair_id, inner_k = 5)
  b <- as.matrix(coef(g$fit, s = "lambda.min"))
  list(model = g, x = imp$train,
       coefs = tibble(feature = rownames(b), coef = b[, 1]) %>% filter(coef != 0))
}

# contribution of each feature to firm i's log-odds relative to the sample-average firm
driver_table <- function(full, feat, firm_code, top = 6) {
  i <- match(firm_code, feat$code)
  cf <- filter(full$coefs, feature != "(Intercept)")
  xc <- sweep(full$x, 2, colMeans(full$x))
  tibble(feature = cf$feature, coef = cf$coef, value = full$x[i, cf$feature],
         contribution = cf$coef * xc[i, cf$feature]) %>%
    arrange(desc(abs(contribution))) %>% head(top)
}
