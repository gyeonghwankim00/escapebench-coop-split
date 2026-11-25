import errno
import unittest
from unittest.mock import Mock
from requests import Response
from requests.exceptions import ChunkedEncodingError, HTTPError
from scripts.download_phi import network_retry, retryable

class RetryTests(unittest.TestCase):
    def test_broken_stream_retries_then_finishes(self):
        operation=Mock(side_effect=[ChunkedEncodingError('Broken pipe'),'done'])
        sleep=Mock()
        self.assertEqual(network_retry(operation,sleep),'done')
        sleep.assert_called_once_with(5)

    def test_bounded_attempts(self):
        operation=Mock(side_effect=ChunkedEncodingError('broken'))
        with self.assertRaises(ChunkedEncodingError):network_retry(operation,Mock())
        self.assertEqual(operation.call_count,4)

    def test_permanent_errors_are_not_retried(self):
        for error in [OSError(errno.EDQUOT,'quota'),PermissionError('denied'),ValueError('incomplete')]:
            self.assertFalse(retryable(error))
        for status,expected in [(401,False),(403,False),(404,False),(429,True),(503,True)]:
            response=Response();response.status_code=status
            self.assertEqual(retryable(HTTPError(response=response)),expected)
