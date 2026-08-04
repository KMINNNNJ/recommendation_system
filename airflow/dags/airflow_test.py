from datetime import datetime

from airflow.sdk import dag, task

@dag(
    dag_id="hello_airflow",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["practice"],
)
def hello_airflow():

    @task
    def start() -> int:
        print("Airflow 실행 성공")
        return 10

    @task
    def calculate(value: int) -> int:
        result = value * 2
        print(f"계산 결과: {result}")
        return result

    @task
    def finish(result: int) -> None:
        print(f"최종 결과: {result}")

    value = start()
    result = calculate(value)
    finish(result)


hello_airflow()