from typing import List, Tuple, Dict, Optional

class Pool:
    """
    Represents a Uniswap V3 pool with two tokens, a fee tier, and a price.
    """
    def __init__(self, token0: str, token1: str, fee: int, sqrt_price_x96: int, liquidity: int):
        self.token0 = token0
        self.token1 = token1
        self.fee = fee  # in hundredths of a bip, e.g. 500 = 0.05%
        self.sqrt_price_x96 = sqrt_price_x96  # sqrt(price) Q96
        self.liquidity = liquidity

    def get_other_token(self, token: str) -> Optional[str]:
        if token == self.token0:
            return self.token1
        elif token == self.token1:
            return self.token0
        return None

    def quote_exact_in(self, token_in: str, amount_in: int) -> Optional[int]:
        """
        Quotes the output amount for a given input amount, using constant product formula.
        This is a simplified version and does not account for ticks or price impact.
        """
        if amount_in <= 0:
            return None
        if token_in == self.token0:
            reserve_in = self.liquidity
            reserve_out = self.liquidity
        elif token_in == self.token1:
            reserve_in = self.liquidity
            reserve_out = self.liquidity
        else:
            return None

        amount_in_with_fee = amount_in * (1_000_000 - self.fee) // 1_000_000
        # x * y = k, so out = (amount_in_with_fee * reserve_out) // (reserve_in + amount_in_with_fee)
        amount_out = (amount_in_with_fee * reserve_out) // (reserve_in + amount_in_with_fee)
        return amount_out

class PoolRegistry:
    """
    Holds all pools and allows querying for pools between token pairs and fee tiers.
    """
    def __init__(self):
        self.pools: List[Pool] = []

    def add_pool(self, pool: Pool) -> None:
        self.pools.append(pool)

    def get_pools(self, token_in: str, token_out: str) -> List[Pool]:
        """
        Returns all pools that connect token_in and token_out.
        """
        result = []
        for pool in self.pools:
            if ({pool.token0, pool.token1} == {token_in, token_out}):
                result.append(pool)
        return result

    def get_best_pool(self, token_in: str, token_out: str, amount_in: int) -> Optional[Pool]:
        """
        Selects the pool (fee tier) that gives the best output for the given input.
        """
        best_pool = None
        best_amount_out = -1
        for pool in self.get_pools(token_in, token_out):
            amount_out = pool.quote_exact_in(token_in, amount_in)
            if amount_out is not None and amount_out > best_amount_out:
                best_amount_out = amount_out
                best_pool = pool
        return best_pool

def find_all_paths(
    registry: PoolRegistry,
    token_in: str,
    token_out: str,
    max_hops: int = 3
) -> List[List[str]]:
    """
    Finds all paths from token_in to token_out up to max_hops.
    """
    paths = []
    def dfs(current: str, target: str, path: List[str], visited: set, hops: int):
        if hops > max_hops:
            return
        if current == target and len(path) > 1:
            paths.append(path[:])
            return
        for pool in registry.pools:
            neighbor = None
            if pool.token0 == current:
                neighbor = pool.token1
            elif pool.token1 == current:
                neighbor = pool.token0
            if neighbor and neighbor not in visited:
                visited.add(neighbor)
                path.append(neighbor)
                dfs(neighbor, target, path, visited, hops + 1)
                path.pop()
                visited.remove(neighbor)
    dfs(token_in, token_out, [token_in], {token_in}, 0)
    return paths

def quote_multi_hop(
    registry: PoolRegistry,
    path: List[str],
    amount_in: int
) -> Tuple[int, List[int], List[int]]:
    """
    Quotes the output amount for a multi-hop swap along the given path.
    Returns (final_amount_out, used_fee_tiers, per_hop_amounts)
    """
    current_amount = amount_in
    used_fee_tiers = []
    per_hop_amounts = [amount_in]
    for i in range(len(path) - 1):
        token_in = path[i]
        token_out = path[i + 1]
        pool = registry.get_best_pool(token_in, token_out, current_amount)
        if pool is None:
            return 0, [], []
        amount_out = pool.quote_exact_in(token_in, current_amount)
        if amount_out is None or amount_out == 0:
            return 0, [], []
        used_fee_tiers.append(pool.fee)
        current_amount = amount_out
        per_hop_amounts.append(current_amount)
    return current_amount, used_fee_tiers, per_hop_amounts

def get_best_multi_hop_quote(
    registry: PoolRegistry,
    token_in: str,
    token_out: str,
    amount_in: int,
    max_hops: int = 3
) -> Dict:
    """
    Finds the best multi-hop path and fee tier selection for a swap.
    Returns a dict with path, fee_tiers, amounts, and final output.
    """
    all_paths = find_all_paths(registry, token_in, token_out, max_hops)
    best_output = -1
    best_result = {}
    for path in all_paths:
        final_out, fee_tiers, amounts = quote_multi_hop(registry, path, amount_in)
        if final_out > best_output:
            best_output = final_out
            best_result = {
                "path": path,
                "fee_tiers": fee_tiers,
                "amounts": amounts,
                "final_output": final_out
            }
    return best_result

# Example usage and test
def _test():
    """
    Simple test for the multi-hop quoting and fee tier selection.
    """
    registry = PoolRegistry()
    # Add pools (token0, token1, fee, sqrt_price_x96, liquidity)
    registry.add_pool(Pool("ETH", "USDC", 500, 79228162514264337593543950336, 10_000_000))
    registry.add_pool(Pool("ETH", "USDC", 3000, 79228162514264337593543950336, 10_000_000))
    registry.add_pool(Pool("USDC", "DAI", 500, 79228162514264337593543950336, 10_000_000))
    registry.add_pool(Pool("ETH", "DAI", 10000, 79228162514264337593543950336, 10_000_000))
    registry.add_pool(Pool("USDC", "WBTC", 3000, 79228162514264337593543950336, 10_000_000))
    registry.add_pool(Pool("WBTC", "DAI", 500, 79228162514264337593543950336, 10_000_000))

    # Direct swap ETH -> DAI
    result1 = get_best_multi_hop_quote(registry, "ETH", "DAI", 1_000_000)
    print("Best direct/multi-hop ETH->DAI:", result1)

    # Multi-hop swap ETH -> USDC -> DAI
    result2 = get_best_multi_hop_quote(registry, "ETH", "DAI", 1_000_000, max_hops=2)
    print("Best 2-hop ETH->DAI:", result2)

    # Multi-hop swap ETH -> USDC -> WBTC -> DAI
    result3 = get_best_multi_hop_quote(registry, "ETH", "DAI", 1_000_000, max_hops=3)
    print("Best 3-hop ETH->DAI:", result3)

if __name__ == "__main__":
    _test()