import logging
import itertools
import pandas as pd
from typing import Dict, List, Any, Type
from .engine import BacktestEngine
from .strategy import Strategy
from .analysis import PerformanceAnalyzer

logger = logging.getLogger(__name__)


def _run_single_backtest(task_args):
    """Helper function to run a single backtest combination. Must be top-level for multiprocessing."""
    (
        idx,
        params,
        data,
        strategy_class,
        initial_cash,
        exchange,
        benchmark_data,
        risk_free_rate,
        engine_kwargs,
    ) = task_args
    from vn_backtest.engine import BacktestEngine
    from vn_backtest.analysis import PerformanceAnalyzer
    import traceback

    try:
        # Merge custom engine kwargs with the current strategy parameters
        kwargs = engine_kwargs.copy()
        if "check_lookahead" not in kwargs:
            kwargs["check_lookahead"] = False

        # Merge global strategy parameters (e.g. SL/TS from CLI) with grid parameters
        combined_strategy_params = params.copy()
        if "strategy_params" in kwargs:
            cli_strat_params = kwargs.pop("strategy_params")
            if cli_strat_params:
                combined_strategy_params.update(cli_strat_params)

        # Instantiate engine
        engine = BacktestEngine(
            data=data,
            strategy_class=strategy_class,
            initial_cash=initial_cash,
            exchange=exchange,
            strategy_params=combined_strategy_params,
            **kwargs,
        )

        # Run backtest
        backtest_res = engine.run()

        # Calculate metrics
        metrics = PerformanceAnalyzer.calculate_metrics(
            equity_curve=backtest_res["equity_curve"],
            trades=backtest_res["trades"],
            benchmark_data=benchmark_data,
            initial_cash=initial_cash,
            risk_free_rate=risk_free_rate,
            include_auto_close=True,
        )

        is_bankrupt = backtest_res.get("is_bankrupt", False)

        # Combine parameters and performance metrics
        record = params.copy()
        if is_bankrupt:
            record.update(
                {
                    "total_return": -1.0,
                    "cagr": -1.0,
                    "sharpe_ratio": -99.0,
                    "sortino_ratio": -99.0,
                    "calmar_ratio": -99.0,
                    "recovery_factor": -99.0,
                    "information_ratio": -99.0,
                    "expectancy": -99.0,
                    "max_drawdown": -1.0,
                    "win_rate": 0.0,
                    "profit_factor": 0.0,
                    "total_trades": metrics.get("total_trades", 0),
                    "is_bankrupt": True,
                }
            )
        else:
            record.update(
                {
                    "total_return": metrics.get("total_return", 0.0),
                    "cagr": metrics.get("cagr", 0.0),
                    "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
                    "sortino_ratio": metrics.get("sortino_ratio", 0.0),
                    "calmar_ratio": metrics.get("calmar_ratio"),
                    "recovery_factor": metrics.get("recovery_factor"),
                    "information_ratio": metrics.get("information_ratio"),
                    "expectancy": metrics.get("expectancy", 0.0),
                    "max_drawdown": metrics.get("max_drawdown", 0.0),
                    "win_rate": metrics.get("win_rate", 0.0),
                    "profit_factor": metrics.get("profit_factor", 0.0),
                    "total_trades": metrics.get("total_trades", 0),
                    "is_bankrupt": False,
                }
            )
        return record, None
    except Exception as e:
        err_msg = f"{e}\n{traceback.format_exc()}"
        return None, (params, err_msg)


class ParameterOptimizer:
    """
    Parameter Optimizer for Grid Searching strategy parameters.
    Runs multiple backtest configurations and compiles performance metrics.
    """

    def __init__(
        self,
        data: Any,
        strategy_class: Type[Strategy],
        param_grid: Dict[str, List[Any]] = None,
        initial_cash: float = 100_000_000.0,
        exchange: Any = "hose",
        benchmark_data: pd.DataFrame = None,
        risk_free_rate: float = 0.04,
        engine_kwargs: Dict[str, Any] = None,
        n_jobs: int = -1,
        param_space: Dict[str, Any] = None,
    ):
        self.data = data
        self.strategy_class = strategy_class
        self.param_grid = param_grid or {}
        self.initial_cash = initial_cash
        self.exchange = exchange
        self.benchmark_data = benchmark_data
        self.risk_free_rate = risk_free_rate
        self.engine_kwargs = engine_kwargs or {}
        self.n_jobs = n_jobs
        self.param_space = param_space

    def run_optimization(
        self, sort_by: str = "sharpe_ratio", ascending: bool = False
    ) -> pd.DataFrame:
        """
        Run the grid search optimization over all parameter combinations.

        Args:
            sort_by (str): Metric to sort results by (e.g. 'sharpe_ratio', 'total_return', 'cagr', 'max_drawdown').
            ascending (bool): True to sort ascending, False to sort descending.

        Returns:
            pd.DataFrame: Optimization results with parameters and metrics.
        """
        # Generate parameter combinations
        keys, values = zip(*self.param_grid.items())
        permutations = [dict(zip(keys, v)) for v in itertools.product(*values)]

        print("=" * 60)
        logger.info(
            f"KHỞI CHẠY TỐI ƯU HÓA THAM SỐ (Tổng cộng {len(permutations)} tổ hợp)"
        )
        print("=" * 60)

        results = []

        if self.n_jobs == 1:
            # Run sequentially
            for idx, params in enumerate(permutations, 1):
                logger.debug(
                    f"[{idx}/{len(permutations)}] Đang chạy thử nghiệm với tham số (tuần tự): {params}..."
                )
                task_args = (
                    idx,
                    params,
                    self.data,
                    self.strategy_class,
                    self.initial_cash,
                    self.exchange,
                    self.benchmark_data,
                    self.risk_free_rate,
                    self.engine_kwargs,
                )
                record, err = _run_single_backtest(task_args)
                if err:
                    logger.error(f"LỖI khi chạy tổ hợp {err[0]}: {err[1]}")
                else:
                    results.append(record)
        else:
            # Run in parallel
            import os
            from concurrent.futures import ProcessPoolExecutor, as_completed

            n_workers = self.n_jobs if self.n_jobs > 0 else os.cpu_count() or 1
            logger.info(f"Chạy song song sử dụng {n_workers} tiến trình...")

            # Prepare task arguments
            tasks = [
                (
                    idx,
                    params,
                    self.data,
                    self.strategy_class,
                    self.initial_cash,
                    self.exchange,
                    self.benchmark_data,
                    self.risk_free_rate,
                    self.engine_kwargs,
                )
                for idx, params in enumerate(permutations, 1)
            ]

            with ProcessPoolExecutor(max_workers=n_workers) as executor:
                # Submit all combinations to the executor
                futures = {
                    executor.submit(_run_single_backtest, task): task for task in tasks
                }

                for future in as_completed(futures):
                    task = futures[future]
                    params = task[1]
                    try:
                        record, err = future.result()
                        if err:
                            logger.error(f"LỖI khi chạy tổ hợp {params}: {err[1]}")
                        else:
                            # Dùng level DEBUG để không làm nhiễu Console, nhưng vẫn tracking được
                            logger.debug(
                                f"[{len(results)+1}/{len(permutations)}] Đã hoàn thành tham số: {record}"
                            )
                            results.append(record)
                    except Exception as e:
                        logger.critical(f"LỖI HỆ THỐNG khi chạy tổ hợp {params}: {e}")

        if not results:
            logger.error("❌ Không chạy thành công bất kỳ tổ hợp tham số nào.")
            return pd.DataFrame()

        results_df = pd.DataFrame(results)

        # Sort results
        if sort_by in results_df.columns:
            results_df.sort_values(by=sort_by, ascending=ascending, inplace=True)

        print("\n" + "=" * 60)
        logger.info("TỐI ƯU HÓA HOÀN TẤT - BẢNG XẾP HẠNG THAM SỐ ĐÃ SẴN SÀNG.")
        print("=" * 60)

        # Display top 5 parameter sets
        top_n = min(5, len(results_df))
        temp_df = results_df.copy()

        # Formatter for pretty printing
        pct_cols = ["total_return", "cagr", "max_drawdown", "win_rate"]
        for col in pct_cols:
            if col in temp_df.columns:
                temp_df[col] = (temp_df[col] * 100).map("{:.2f}%".format)

        ratio_cols = ["sharpe_ratio", "sortino_ratio", "profit_factor"]
        for col in ratio_cols:
            if col in temp_df.columns:
                temp_df[col] = temp_df[col].map("{:.2f}".format)

        print(temp_df.head(top_n).to_string(index=False))
        print("=" * 60 + "\n")

        return results_df

    def run_optuna(
        self,
        n_trials: int = 50,
        sort_by: str = "sharpe_ratio",
        ascending: bool = False,
        sampler: str = "tpe",
        param_space: Dict[str, Any] = None,
    ) -> pd.DataFrame:
        """
        Run parameter optimization using Optuna's Bayesian optimization.

        Args:
            n_trials (int): Number of optimization trials to run.
            sort_by (str): Metric to maximize/minimize.
            ascending (bool): If True, minimize. If False, maximize.
            sampler (str): Sampler type ('tpe' or 'random').
            param_space (Dict[str, Any], optional): Dictionary defining the search space.
                Example:
                    param_space = {
                        "sma_fast": ("int", 5, 20),
                        "stop_loss": ("float", 0.01, 0.1),
                        "order_type": ("categorical", ["ATO", "ATC", "LIMIT"])
                    }

        Returns:
            pd.DataFrame: Optimization results with parameters and metrics.
        """
        try:
            import optuna
        except ImportError:
            raise ImportError(
                "Thư viện 'optuna' chưa được cài đặt. Vui lòng cài đặt bằng lệnh:\n"
                "pip install optuna"
            )

        print("=" * 60)
        logger.info(
            f"KHỞI CHẠY TỐI ƯU HÓA OPTUNA (Số lượt chạy thử nghiệm: {n_trials})"
        )
        print("=" * 60)

        # Optuna logging level
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        # Resolve param space (use instance param_space or param_grid if none provided)
        resolved_space = param_space or self.param_space
        if resolved_space is None:
            resolved_space = {k: ("categorical", v) for k, v in self.param_grid.items()}

        # Objective function
        def objective(trial):
            # Suggest parameters
            params = {}
            for param_name, config in resolved_space.items():
                if isinstance(config, (list, tuple)) and len(config) > 0:
                    opt_type = config[0]
                    if opt_type == "int" and len(config) >= 3:
                        low, high = config[1], config[2]
                        step = config[3] if len(config) > 3 else 1
                        params[param_name] = trial.suggest_int(param_name, low, high, step=step)
                    elif opt_type == "float" and len(config) >= 3:
                        low, high = config[1], config[2]
                        step = config[3] if len(config) > 3 else None
                        log = config[4] if len(config) > 4 else False
                        params[param_name] = trial.suggest_float(param_name, low, high, step=step, log=log)
                    elif opt_type == "categorical" and len(config) >= 2:
                        choices = config[1]
                        params[param_name] = trial.suggest_categorical(param_name, choices)
                    else:
                        # Fallback for config being a raw list of choices
                        params[param_name] = trial.suggest_categorical(param_name, config)
                else:
                    # Fallback to categorical choice
                    params[param_name] = trial.suggest_categorical(param_name, [config] if not isinstance(config, list) else config)

            # Run backtest
            task_args = (
                trial.number,
                params,
                self.data,
                self.strategy_class,
                self.initial_cash,
                self.exchange,
                self.benchmark_data,
                self.risk_free_rate,
                self.engine_kwargs,
            )
            record, err = _run_single_backtest(task_args)

            if err:
                # If backtest fails, return a bad value
                logger.error(
                    f"Optuna Trial {trial.number} failed with parameters {params}: {err[1]}"
                )
                return float("-inf") if not ascending else float("inf")

            # Store the metrics on the trial for later retrieval
            for key, val in record.items():
                trial.set_user_attr(key, val)

            if record.get("is_bankrupt", False):
                # Penalize bankruptcy by returning worst possible value
                return float("-inf") if not ascending else float("inf")

            # Return target metric to optimize
            return record.get(sort_by, 0.0)

        # Create study
        direction = "minimize" if ascending else "maximize"
        if sampler == "tpe":
            opt_sampler = optuna.samplers.TPESampler()
        else:
            opt_sampler = optuna.samplers.RandomSampler()

        study = optuna.create_study(
            direction=direction,
            sampler=opt_sampler,
        )

        study.optimize(objective, n_trials=n_trials)

        # Compile results
        results = []
        for trial in study.trials:
            if trial.state == optuna.trial.TrialState.COMPLETE:
                res = trial.user_attrs.copy()
                results.append(res)

        if not results:
            logger.error("❌ Không chạy thành công bất kỳ thử nghiệm Optuna nào.")
            return pd.DataFrame()

        results_df = pd.DataFrame(results)

        # Sort results
        if sort_by in results_df.columns:
            results_df.sort_values(by=sort_by, ascending=ascending, inplace=True)

        print("\n" + "=" * 60)
        logger.info("TỐI ƯU HÓA OPTUNA HOÀN TẤT - BẢNG XẾP HẠNG THAM SỐ ĐÃ SẴN SÀNG.")
        print("=" * 60)

        # Display top 5 parameter sets
        top_n = min(5, len(results_df))
        temp_df = results_df.copy()

        # Formatter for pretty printing
        pct_cols = ["total_return", "cagr", "max_drawdown", "win_rate"]
        for col in pct_cols:
            if col in temp_df.columns:
                temp_df[col] = (temp_df[col] * 100).map("{:.2f}%".format)

        ratio_cols = ["sharpe_ratio", "sortino_ratio", "profit_factor"]
        for col in ratio_cols:
            if col in temp_df.columns:
                temp_df[col] = temp_df[col].map("{:.2f}".format)

        print(temp_df.head(top_n).to_string(index=False))
        print("=" * 60 + "\n")

        return results_df
