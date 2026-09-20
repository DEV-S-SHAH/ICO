package main

import "errors"

// CalculateMargin computes net operating margin percentage
func CalculateMargin(revenue float64, cost float64) (float64, error) {
    if revenue <= 0 {
        return 0, errors.New("revenue must be positive")
    }
    return (revenue - cost) / revenue, nil
}

// ComputeTax calculates tax amount based on regional tax rate
func ComputeTax(subtotal float64, taxRate float64) float64 {
    if taxRate < 0 {
        return 0
    }
    return subtotal * taxRate
}

// FinancialLedger tracks balance and transactions across quarters
type FinancialLedger struct {
    TenantID string
    Balance  float64
    Quarter  string
}
