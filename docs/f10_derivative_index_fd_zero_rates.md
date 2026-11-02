# f10_derivative_index_fd 零值率统计

- 生成时间：2026-11-01 17:06
- 表：`dws.f10_derivative_index_fd`
- 总行数：321,697
- 总列数：676
- 数值列：652
- 字符串列：22
- 日期/时间列：2

## 口径

- 数值列：`countIf(field = 0) / count()`
- 字符串列：统计空字符串比例，`zero_rate` 留空
- 日期/时间列：不适用，`zero_rate` 留空
- 未做 Mark / BulletinType 过滤，统计的是整张表
- 该表已从系统字段目录移除，本统计仅作数据质量参考

## 零值率分布（数值列）

| 区间 | 字段数 |
|---|---:|
| 100%（精确全 0） | 0 |
| > 99%（含近似全 0） | 161 |
| 90%–99% | 71 |
| 50%–90% | 83 |
| 10%–50% | 181 |
| < 10% | 156 |

全 0 字段：0 个。

## 零值率最高的 50 个数值字段

| 序号 | 字段 | 类型 | 零值率 | 说明 |
|---:|---|---|---:|---|
| 1 | `OtherReserves` | Decimal(38, 4) | 99.9963% | 其他储备(公允价值变动储备)(元) |
| 2 | `BearerBiologicalAssets` | Decimal(38, 4) | 99.9950% | 其中:消耗性生物资产 |
| 3 | `DebtAssets` | Decimal(38, 4) | 99.9919% | 抵债资产 |
| 4 | `ImpawnedLoan` | Decimal(38, 4) | 99.9913% | 其中:质押借款(元) |
| 5 | `DebitofAssociate` | Decimal(38, 4) | 99.9907% | 联行存放款项 |
| 6 | `DepositsReceived` | Decimal(38, 4) | 99.9888% | 存入保证金 |
| 7 | `OCIToMaturityFA` | Decimal(38, 4) | 99.9885% | 2.3持有至到期投资重分类为可供出售金融资产损益 |
| 8 | `CorporateCRChange` | Decimal(38, 4) | 99.9873% | 1.4企业自身信用风险公允价值变动 |
| 9 | `OtherItemsEffectingCEI` | Decimal(38, 4) | 99.9857% | ##现金及现金等价物净增加额的特殊项目 |
| 10 | `DepositInAssociate` | Decimal(38, 4) | 99.9848% | 存放联行款项 |
| 11 | `FinLeasesPayable` | Decimal(38, 4) | 99.9773% | 应付融资租赁款 |
| 12 | `LPreferStock` | Decimal(38, 4) | 99.9742% | 其中:优先股(应付债券)(元) |
| 13 | `LPerpetualDebt` | Decimal(38, 4) | 99.9705% | 其中:永续债(应付债券)(元) |
| 14 | `NetIncCapResBusInv` | Decimal(38, 4) | 99.9705% | 返售业务资金净增加额(投资) |
| 15 | `CBsExpiringWithin1Y` | Decimal(38, 4) | 99.9677% | 一年内到期的可转换公司债券 |
| 16 | `PreInsurRSRV` | Decimal(38, 4) | 99.9664% | 提取保费准备金 |
| 17 | `ReceivableSubrogationFee` | Decimal(38, 4) | 99.9643% | 应收代位追偿款 |
| 18 | `NetOpenHedgeIncome` | Decimal(38, 4) | 99.9633% | 净敞口套期收益 |
| 19 | `OtherItemsEffectingNPP` | Decimal(38, 4) | 99.9618% | ##加:影响母公司净利润的特殊项目 |
| 20 | `AdjustmentItemsFCIF` | Decimal(38, 4) | 99.9593% | ##筹资活动现金流入调整项目 |
| 21 | `OtherItemsEffectingCE` | Decimal(38, 4) | 99.9562% | ##影响现金及现金等价物的其他科目 |
| 22 | `SpecialItemsC` | Decimal(38, 4) | 99.9512% | ##(附注)现金特殊项目 |
| 23 | `CashRecIssOthEquIns` | Decimal(38, 4) | 99.9506% | 发行其他权益工具收到的现金 |
| 24 | `NetCashRecAgeUTS` | Decimal(38, 4) | 99.9506% | 代理承销证券收到的现金净额 |
| 25 | `NetBuyBackFin` | Decimal(38, 4) | 99.9475% | 回购业务资金净增加额(筹资) |
| 26 | `LEExceptionalItems` | Decimal(38, 4) | 99.9447% | ##负债和权益特殊项目 |
| 27 | `AdjustmentItemsOR` | Decimal(38, 4) | 99.9422% | ##营业收入调整项目 |
| 28 | `DrawBackLoansCanceled` | Decimal(38, 4) | 99.9416% | 收回已核销贷款 |
| 29 | `FinLeaseReceivable` | Decimal(38, 4) | 99.9388% | 应收融资租赁款 |
| 30 | `IndependenceLiability` | Decimal(38, 4) | 99.9316% | 独立账户负债 |
| 31 | `AdjustmentItemsICOF` | Decimal(38, 4) | 99.9313% | ##投资活动现金流出调整项目 |
| 32 | `IndependenceAccountAssets` | Decimal(38, 4) | 99.9304% | 独立账户资产 |
| 33 | `NetReinsuranceCash` | Decimal(38, 4) | 99.9291% | 收到再保业务现金净额 |
| 34 | `ReceivableLifeR` | Decimal(38, 4) | 99.9269% | 应收分保寿险责任准备金(元) |
| 35 | `LTHealthInsuranceLR` | Decimal(38, 4) | 99.9248% | 长期健康险责任准备金 |
| 36 | `ReceivableLTHealthR` | Decimal(38, 4) | 99.9248% | 应收分保长期健康险责任准备金 |
| 37 | `LifeInsuranceReserve` | Decimal(38, 4) | 99.9245% | 寿险责任准备金 |
| 38 | `AdjustmentItemsICIF` | Decimal(38, 4) | 99.9214% | ##投资活动现金流入调整项目 |
| 39 | `AdjustmentItemsNFCF` | Decimal(38, 4) | 99.9182% | ##筹资活动流量现金净额调整项目 |
| 40 | `ReinsuranceIncome` | Decimal(38, 4) | 99.9145% | 其中:分保费收入 |
| 41 | `NetInsurerDepositInvestment` | Decimal(38, 4) | 99.9139% | 保户储金及投资款净增加额 |
| 42 | `NCLAdjustmentItems` | Decimal(38, 4) | 99.9133% | ##非流动负债调整项目 |
| 43 | `InsurerImpawnLoan` | Decimal(38, 4) | 99.9108% | 保户质押贷款 |
| 44 | `PolicyDividendPayable` | Decimal(38, 4) | 99.9080% | 应付保单红利 |
| 45 | `OutstandingClaimReserve` | Decimal(38, 4) | 99.9052% | 未决赔款准备金 |
| 46 | `InsurerDepositInvestment` | Decimal(38, 4) | 99.9049% | 保户储金及投资款 |
| 47 | `ReceivableClaimsR` | Decimal(38, 4) | 99.9027% | 应收分保未决赔款准备金 |
| 48 | `ReinsuranceCost` | Decimal(38, 4) | 99.8999% | 分保费用 |
| 49 | `AdjustmentItemsFCOF` | Decimal(38, 4) | 99.8980% | ##筹资活动现金流出调整项目 |
| 50 | `InsContractReserve` | Decimal(38, 4) | 99.8956% | 保险合同准备金 |

## 字符串字段空值率

| 字段 | 类型 | 空字符串率 | 说明 |
|---|---|---:|---|
| `FourthIndustryCode` | String | 100.0000% | 四级行业代码 |
| `FourthIndustryName` | String | 100.0000% | 四级行业名称 |
| `FirstIndustryCode` | String | 0.5968% | 一级行业代码 |
| `FirstIndustryName` | String | 0.5968% | 一级行业名称 |
| `SecondIndustryCode` | String | 0.5968% | 二级行业代码 |
| `SecondIndustryName` | String | 0.5968% | 二级行业名称 |
| `ThirdIndustryCode` | String | 0.5968% | 三级行业代码 |
| `ThirdIndustryName` | String | 0.5968% | 三级行业名称 |
| `ChiName` | String | 0.0000% | 中文名称 |
| `ChiNameAbbr` | String | 0.0000% | 中文名称缩写 |
| `ChiSpelling` | String | 0.0000% | 拼音证券简称 |
| `CompanyCode` | String | 0.0000% | 公司代码 |
| `EngName` | String | 0.0000% | 英文名称 |
| `EngNameAbbr` | String | 0.0000% | 英文名称缩写 |
| `Industry` | String | 0.0000% | 所属行业 |
| `InnerCode` | String | 0.0000% | 证券内部编码 |
| `ListedSector` | String | 0.0000% | 上市板块 |
| `ListedState` | String | 0.0000% | 上市状态 |
| `SecuAbbr` | String | 0.0000% | 证券简称 |
| `SecuCategory` | String | 0.0000% | 证券类别 |
| `SecuCode` | String | 0.0000% | 股票代码 |
| `SecuMarket` | String | 0.0000% | 证券市场 |

## 完整结果

全部 676 列的逐字段结果见：`f10_derivative_index_fd_zero_rates.csv`。
