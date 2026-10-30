---
title: معرفی فارسی
---

<div dir="rtl" markdown>

# معرفی فارسی

**llm-search-eval** ابزاری متن باز برای سنجش کیفیت جستجو و پیشنهاد محصول در فروشگاه های اینترنتی است. این ابزار معیارهای کلاسیک بازیابی اطلاعات مانند nDCG و MRR و MAP را با داوری مدل های زبانی ترکیب می کند تا نتایجی که برچسب ندارند هم ارزیابی شوند. چند سیستم جستجو را کنار هم مقایسه می کند و برای هر مقایسه آزمون معناداری آماری ارائه می دهد. پرسش های فارسی و انگلیسی هر دو پشتیبانی می شوند و نویسه های عربی، ارقام فارسی و فاصله های مجازی به شکل یکسان نرمال سازی می شوند.

در نسخه 0.2.0 چند داور مدل زبانی می توانند با هم رای بدهند و میزان توافق آن ها با شاخص های کاپای کوهن، کاپای فلایس و آلفای کریپندورف گزارش می شود. هزینه و توکن هر اجرا با سقف بودجه کنترل می شود. گزارش تعاملی HTML در یک فایل مستقل ساخته می شود. یک GitHub Action آماده هم هست که در صورت افت کیفیت جستجو، بررسی را ناموفق می کند. اتصال مستقیم به Elasticsearch و OpenSearch و Algolia هم اضافه شده است.

## شروع سریع

</div>

```bash
pip install llm-search-eval
llm-search-eval run \
  --queries  examples/electronics/queries.jsonl \
  --products examples/electronics/products.jsonl \
  --qrels    examples/electronics/qrels.csv \
  --system   bm25=examples/electronics/runs/bm25.jsonl \
  --system   semantic=examples/electronics/runs/semantic.csv \
  --judge mock --output-dir reports/
```

<div dir="rtl" markdown>

این دستور با داور آزمایشی و بدون نیاز به اینترنت اجرا می شود و گزارش Markdown و JSON و داشبورد HTML را در پوشه reports می سازد. برای دیدن نمونه خروجی، [داشبورد نمونه](https://sadrmanesh.github.io/llm-search-eval/demo/report.html) را باز کنید.

## راهنماها

- [شروع کار](getting-started.md)
- [قالب داده ها](data-formats.md)
- [داوری مرتبط بودن](relevance-judges.md)
- [چند داور و میزان توافق](judges.md)
- [هزینه و بودجه](cost.md)
- [گزارش ها و داشبورد](reports.md)
- [کنترل کیفیت در CI](ci.md)
- [اتصال به موتورهای جستجو](connectors.md)
- [پشتیبانی از زبان فارسی](persian.md)

</div>
