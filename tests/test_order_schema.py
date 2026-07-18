import io
import unittest

import pandas as pd

from clean_pipeline import clean_pipeline
from order_schema import (
    normalize_status_value,
    parse_datetime_value,
    parse_number,
    read_single_sheet_order_file,
    suggest_column_mapping,
    validate_mapped_orders,
)


class UploadedFileStub:
    def __init__(self, name, content):
        self.name = name
        self._content = content

    def getvalue(self):
        return self._content


class OrderSchemaTests(unittest.TestCase):
    def test_common_business_headers(self):
        headers = [
            "商家订单编号", "买家UID", "SKU编码", "商品标题", "支付成功时间",
            "成交件数", "成交单价", "订单实收金额", "交易状态", "收货城市",
        ]
        mapping = suggest_column_mapping(headers)
        self.assertEqual(mapping["order_id"], "商家订单编号")
        self.assertEqual(mapping["order_date"], "支付成功时间")
        self.assertEqual(mapping["total_amount"], "订单实收金额")

    def test_numbers_dates_and_statuses(self):
        self.assertEqual(parse_number("￥1,299.00"), 1299.0)
        self.assertEqual(parse_number("1.2万"), 12000.0)
        self.assertEqual(str(parse_datetime_value(45292).date()), "2024-01-01")
        self.assertEqual(normalize_status_value("交易成功"), "completed")
        self.assertEqual(normalize_status_value("退款中"), "refunded")

    def test_no_date_is_allowed_and_user_paid_is_preferred(self):
        mapping = suggest_column_mapping(["订单号", "商品总价", "用户实付", "售后状态"])
        self.assertEqual(mapping["total_amount"], "用户实付")
        errors, warnings = validate_mapped_orders(pd.DataFrame({
            "order_id": ["A1"],
            "total_amount": [99],
        }))
        self.assertEqual(errors, [])
        self.assertTrue(any("缺少订单时间" in message for message in warnings))

    def test_csv_header_detection_with_title_rows(self):
        content = (
            "订单报表,,,\n"
            "统计周期：本周,,,\n"
            "订单号,支付时间,实付金额,订单状态\n"
            "A1,2026-07-01,99,交易成功\n"
        ).encode("gb18030")
        df, info = read_single_sheet_order_file(UploadedFileStub("orders.csv", content))
        self.assertEqual(info["header_row"], 3)
        self.assertEqual(df.columns.tolist(), ["订单号", "支付时间", "实付金额", "订单状态"])

    def test_excel_reads_first_sheet_only(self):
        first_sheet = pd.DataFrame([
            ["订单导出", None, None],
            ["订单编号", "成交时间", "成交金额"],
            ["A1", "2026-07-01", 99],
        ])
        second_sheet = pd.DataFrame([["不应读取"], ["B1"]])
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            first_sheet.to_excel(writer, index=False, header=False, sheet_name="订单")
            second_sheet.to_excel(writer, index=False, header=False, sheet_name="其他")
        df, info = read_single_sheet_order_file(UploadedFileStub("orders.xlsx", buffer.getvalue()))
        self.assertEqual(info["sheet"], "第一个Sheet")
        self.assertEqual(df.loc[0, "订单编号"], "A1")
        self.assertNotIn("不应读取", df.columns)

    def test_cleaning_preserves_zero_and_order_lines(self):
        raw = pd.DataFrame({
            "order_id": ["A1", "A1", "A2"],
            "order_date": ["2026-07-01", "2026-07-01", "2026-07-02"],
            "quantity": [1, 2, 1],
            "unit_price": [10, 20, 99],
            "total_amount": [10, 40, 0],
            "status": ["交易成功", "交易成功", "已完成"],
            "product_name": ["甲", "乙", "赠品"],
        })
        cleaned, report = clean_pipeline(raw)
        self.assertEqual(len(cleaned), 3)
        self.assertEqual(cleaned.loc[cleaned["order_id"] == "A2", "total_amount"].iloc[0], 0)
        self.assertTrue(any("2 个去重订单" in item for item in report))


if __name__ == "__main__":
    unittest.main()
