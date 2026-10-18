"""Exercise chat request success/failure without external API calls."""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import requests
from streamlit.testing.v1 import AppTest


APP=Path(__file__).resolve().parents[1]/"streamlit/streamlit.py"


class ServiceUiTests(unittest.TestCase):
    def started_app(self):
        app=AppTest.from_file(str(APP)).run(timeout=20)
        app.button[0].click().run(timeout=20)
        self.assertEqual(len(app.exception),0)
        return app

    def test_success_keeps_readable_answer_container_and_chat_history(self):
        app=self.started_app()
        response=Mock(status_code=200)
        response.json.return_value={"type":"general_question","answer":"테스트 답변입니다.","result":{}}
        with patch("requests.post",return_value=response) as post:
            app.chat_input[0].set_value("테스트 질문").run(timeout=20)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state.messages[-1]["data"]["answer"],"테스트 답변입니다.")
        self.assertEqual(post.call_count,1)
        # Rendering stored history again must not reuse a container key.
        app.run(timeout=20)
        self.assertEqual(len(app.exception),0)

    def test_timeout_is_visible_and_does_not_add_success_message(self):
        app=self.started_app()
        with patch("requests.post",side_effect=requests.exceptions.Timeout):
            app.chat_input[0].set_value("테스트 질문").run(timeout=20)
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any("시간" in error.value for error in app.error))
        self.assertEqual(app.session_state.messages[-1]["role"],"user")


if __name__=="__main__":
    unittest.main()
