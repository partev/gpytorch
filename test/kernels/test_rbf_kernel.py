#!/usr/bin/env python3

import math
import pickle
import unittest

import torch

from gpytorch.kernels import RBFKernel
from gpytorch.kernels.rbf_kernel import rbf_forward, rbf_vjp, SparseBilinearForm
from gpytorch.priors import NormalPrior
from gpytorch.test.base_kernel_test_case import BaseKernelTestCase


class TestRBFKernel(unittest.TestCase, BaseKernelTestCase):
    def create_kernel_no_ard(self, **kwargs):
        return RBFKernel(**kwargs)

    def create_kernel_ard(self, num_dims, **kwargs):
        return RBFKernel(ard_num_dims=num_dims, **kwargs)

    def test_ard(self):
        a = torch.tensor([[1, 2], [2, 4]], dtype=torch.float)
        b = torch.tensor([[1, 3], [0, 4]], dtype=torch.float)
        lengthscales = torch.tensor([1, 2], dtype=torch.float).view(1, 2)

        kernel = RBFKernel(ard_num_dims=2)
        kernel.initialize(lengthscale=lengthscales)
        kernel.eval()

        scaled_a = a.div(lengthscales)
        scaled_b = b.div(lengthscales)
        actual = (scaled_a.unsqueeze(-2) - scaled_b.unsqueeze(-3)).pow(2).sum(dim=-1).mul_(-0.5).exp()
        res = kernel(a, b).to_dense()
        self.assertLess(torch.norm(res - actual), 1e-5)

        # Diag
        res = kernel(a, b).diagonal(dim1=-1, dim2=-2)
        actual = actual.diagonal(dim1=-1, dim2=-2)
        self.assertLess(torch.norm(res - actual), 1e-5)

        # batch_dims
        actual = scaled_a.transpose(-1, -2).unsqueeze(-1) - scaled_b.transpose(-1, -2).unsqueeze(-2)
        actual = actual.pow(2).mul_(-0.5).exp()
        res = kernel(a, b, last_dim_is_batch=True).to_dense()
        self.assertLess(torch.norm(res - actual), 1e-5)

        # batch_dims and diag
        res = kernel(a, b, last_dim_is_batch=True).diagonal(dim1=-1, dim2=-2)
        actual = actual.diagonal(dim1=-1, dim2=-2)
        self.assertLess(torch.norm(res - actual), 1e-5)

    def test_ard_batch(self):
        a = torch.tensor([[[1, 2, 3], [2, 4, 0]], [[-1, 1, 2], [2, 1, 4]]], dtype=torch.float)
        b = torch.tensor([[[1, 3, 1]], [[2, -1, 0]]], dtype=torch.float).repeat(1, 2, 1)
        lengthscales = torch.tensor([[[1, 2, 1]]], dtype=torch.float)

        kernel = RBFKernel(batch_shape=torch.Size([2]), ard_num_dims=3)
        kernel.initialize(lengthscale=lengthscales)
        kernel.eval()

        scaled_a = a.div(lengthscales)
        scaled_b = b.div(lengthscales)
        actual = (scaled_a.unsqueeze(-2) - scaled_b.unsqueeze(-3)).pow(2).sum(dim=-1).mul_(-0.5).exp()
        res = kernel(a, b).to_dense()
        self.assertLess(torch.norm(res - actual), 1e-5)

        # diag
        res = kernel(a, b).diagonal(dim1=-1, dim2=-2)
        actual = actual.diagonal(dim1=-1, dim2=-2)
        self.assertLess(torch.norm(res - actual), 1e-5)

        # batch_dims
        double_batch_a = scaled_a.transpose(-1, -2).unsqueeze(-1)
        double_batch_b = scaled_b.transpose(-1, -2).unsqueeze(-2)
        actual = double_batch_a - double_batch_b
        actual = actual.pow(2).mul_(-0.5).exp()
        res = kernel(a, b, last_dim_is_batch=True).to_dense()
        self.assertLess(torch.norm(res - actual), 1e-5)

        # batch_dims and diag
        res = kernel(a, b, last_dim_is_batch=True).diagonal(dim1=-1, dim2=-2)
        actual = actual.diagonal(dim1=-2, dim2=-1)
        self.assertLess(torch.norm(res - actual), 1e-5)

    def test_ard_separate_batch(self):
        a = torch.tensor([[[1, 2, 3], [2, 4, 0]], [[-1, 1, 2], [2, 1, 4]]], dtype=torch.float)
        b = torch.tensor([[[1, 3, 1]], [[2, -1, 0]]], dtype=torch.float).repeat(1, 2, 1)
        lengthscales = torch.tensor([[[1, 2, 1]], [[2, 1, 0.5]]], dtype=torch.float)

        kernel = RBFKernel(batch_shape=torch.Size([2]), ard_num_dims=3)
        kernel.initialize(lengthscale=lengthscales)
        kernel.eval()

        scaled_a = a.div(lengthscales)
        scaled_b = b.div(lengthscales)
        actual = (scaled_a.unsqueeze(-2) - scaled_b.unsqueeze(-3)).pow(2).sum(dim=-1).mul_(-0.5).exp()
        res = kernel(a, b).to_dense()
        self.assertLess(torch.norm(res - actual), 1e-5)

        # diag
        res = kernel(a, b).diagonal(dim1=-1, dim2=-2)
        actual = actual.diagonal(dim1=-1, dim2=-2)
        self.assertLess(torch.norm(res - actual), 1e-5)

    def test_subset_active_compute_radial_basis_function(self):
        a = torch.tensor([4, 2, 8], dtype=torch.float).view(3, 1)
        a_p = torch.tensor([1, 2, 3], dtype=torch.float).view(3, 1)
        a = torch.cat((a, a_p), 1)
        b = torch.tensor([0, 2, 4], dtype=torch.float).view(3, 1)
        lengthscale = 2

        kernel = RBFKernel(active_dims=[0])
        kernel.initialize(lengthscale=lengthscale)
        kernel.eval()

        actual = torch.tensor([[16, 4, 0], [4, 0, 4], [64, 36, 16]], dtype=torch.float)
        actual.mul_(-0.5).div_(lengthscale**2).exp_()
        res = kernel(a, b).to_dense()
        self.assertLess(torch.norm(res - actual), 1e-5)

        # diag
        res = kernel(a, b).diagonal(dim1=-1, dim2=-2)
        actual = actual.diagonal(dim1=-1, dim2=-2)
        self.assertLess(torch.norm(res - actual), 1e-5)

    def test_computes_radial_basis_function(self):
        a = torch.tensor([4, 2, 8], dtype=torch.float).view(3, 1)
        b = torch.tensor([0, 2, 4], dtype=torch.float).view(3, 1)
        lengthscale = 2

        kernel = RBFKernel().initialize(lengthscale=lengthscale)
        kernel.eval()

        actual = torch.tensor([[16, 4, 0], [4, 0, 4], [64, 36, 16]], dtype=torch.float)
        actual.mul_(-0.5).div_(lengthscale**2).exp_()
        res = kernel(a, b).to_dense()
        self.assertLess(torch.norm(res - actual), 1e-5)

        # diag
        res = kernel(a, b).diagonal(dim1=-1, dim2=-2)
        actual = actual.diagonal(dim1=-1, dim2=-2)
        self.assertLess(torch.norm(res - actual), 1e-5)

    def test_computes_radial_basis_function_gradient(self):
        softplus = torch.nn.functional.softplus
        a = torch.tensor([4, 2, 8], dtype=torch.float).view(3, 1)
        b = torch.tensor([0, 2, 2], dtype=torch.float).view(3, 1)
        lengthscale = 2

        kernel = RBFKernel().initialize(lengthscale=lengthscale)
        kernel.eval()

        param = math.log(math.exp(lengthscale) - 1) * torch.ones(3, 3)
        param.requires_grad_()
        diffs = a.expand(3, 3) - b.expand(3, 3).transpose(0, 1)
        actual_output = (-0.5 * (diffs / softplus(param)) ** 2).exp()
        actual_output.backward(gradient=torch.eye(3))
        actual_param_grad = param.grad.sum()

        output = kernel(a, b).to_dense()
        output.backward(gradient=torch.eye(3))
        res = kernel.raw_lengthscale.grad

        self.assertLess(torch.norm(res - actual_param_grad), 1e-5)

    def test_subset_active_computes_radial_basis_function_gradient(self):
        softplus = torch.nn.functional.softplus
        a_1 = torch.tensor([4, 2, 8], dtype=torch.float).view(3, 1)
        a_p = torch.tensor([1, 2, 3], dtype=torch.float).view(3, 1)
        a = torch.cat((a_1, a_p), 1)
        b = torch.tensor([0, 2, 2], dtype=torch.float).view(3, 1)
        lengthscale = 2

        param = math.log(math.exp(lengthscale) - 1) * torch.ones(3, 3)
        param.requires_grad_()
        diffs = a_1.expand(3, 3) - b.expand(3, 3).transpose(0, 1)
        actual_output = (-0.5 * (diffs / softplus(param)) ** 2).exp()
        actual_output.backward(torch.eye(3))
        actual_param_grad = param.grad.sum()

        kernel = RBFKernel(active_dims=[0])
        kernel.initialize(lengthscale=lengthscale)
        kernel.eval()
        output = kernel(a, b).to_dense()
        output.backward(gradient=torch.eye(3))
        res = kernel.raw_lengthscale.grad

        self.assertLess(torch.norm(res - actual_param_grad), 1e-5)

    def test_initialize_lengthscale(self):
        kernel = RBFKernel()
        kernel.initialize(lengthscale=3.14)
        actual_value = torch.tensor(3.14).view_as(kernel.lengthscale)
        self.assertLess(torch.norm(kernel.lengthscale - actual_value), 1e-5)

    def test_initialize_lengthscale_batch(self):
        kernel = RBFKernel(batch_shape=torch.Size([2]))
        ls_init = torch.tensor([3.14, 4.13])
        kernel.initialize(lengthscale=ls_init)
        actual_value = ls_init.view_as(kernel.lengthscale)
        self.assertLess(torch.norm(kernel.lengthscale - actual_value), 1e-5)

    def create_kernel_with_prior(self, lengthscale_prior):
        return self.create_kernel_no_ard(lengthscale_prior=lengthscale_prior)

    def test_prior_type(self):
        """
        Raising TypeError if prior type is other than gpytorch.priors.Prior
        """
        self.create_kernel_with_prior(None)
        self.create_kernel_with_prior(NormalPrior(0, 1))
        self.assertRaises(TypeError, self.create_kernel_with_prior, 1)

    def test_pickle_with_prior(self):
        kernel = self.create_kernel_with_prior(NormalPrior(0, 1))
        pickle.loads(pickle.dumps(kernel))  # Should be able to pickle and unpickle with a prior

    def test_custom_forward_and_vjp(self):
        x1 = torch.randn(2, 4, 6, 3).requires_grad_(True)
        x2 = torch.randn(2, 4, 5, 3).requires_grad_(True)
        x1_clone = x1.detach().clone()
        x2_clone = x2.detach().clone()

        # Actual forward
        kernel = RBFKernel()
        kernel.lengthscale = 1.0
        K = kernel(x1, x2).to_dense()

        # Test custom forward
        K_custom = rbf_forward(x1_clone, x2_clone)
        self.assertAllClose(K, K_custom)

        # Actual backward
        V = torch.randn(2, 4, 6, 5)
        K.backward(gradient=V)

        # Test custom backward
        x1_grad, x2_grad = rbf_vjp(V, x1_clone, x2_clone)
        self.assertAllClose(x1.grad, x1_grad)
        self.assertAllClose(x2.grad, x2_grad)

    def test_sparse_bilinear_form(self):
        N = 8
        D = 5
        K = 3
        I1 = 4
        I2 = 2
        X = torch.randn(4, N, D).requires_grad_(True)
        Sv1 = torch.randn(4, K, I1).requires_grad_(True)
        Si1 = torch.stack([torch.randperm(N) for _ in range(I1)], dim=-1)[..., :K, :]
        Sv2 = torch.randn(2, 1, K, I2).requires_grad_(True)
        Si2 = torch.stack([torch.randperm(N) for _ in range(I2)], dim=-1)[..., :K, :]
        X_clone = X.detach().clone().requires_grad_(True)
        Sv1_clone = Sv1.detach().clone().requires_grad_(True)
        Sv2_clone = Sv2.detach().clone().requires_grad_(True)

        # Actual forward
        kernel = RBFKernel()
        kernel.lengthscale = 1.0
        _shape1 = torch.Size([2, 4, K, I1])
        _shape2 = torch.Size([2, 4, K, I2])
        S1 = torch.zeros(2, 4, N, I1).scatter_(-2, Si1.expand(_shape1), Sv1.expand(_shape1))
        S2 = torch.zeros(2, 4, N, I2).scatter_(-2, Si2.expand(_shape2), Sv2.expand(_shape2))
        S1T_K_S2 = S1.mT @ kernel(X, X).to_dense() @ S2

        # Test custom forward
        S1T_K_S2_custom = SparseBilinearForm.apply(X_clone, Sv1_clone, Sv2_clone, Si1, Si2, rbf_forward, rbf_vjp, 1)
        self.assertAllClose(S1T_K_S2, S1T_K_S2_custom)

        # Actual backward
        V = torch.randn(2, 4, I1, I2)
        S1T_K_S2.backward(gradient=V)

        # Test custom backward
        S1T_K_S2_custom.backward(gradient=V)
        self.assertAllClose(X.grad, X_clone.grad)
        self.assertAllClose(Sv1.grad, Sv1_clone.grad)
        self.assertAllClose(Sv2.grad, Sv2_clone.grad)


if __name__ == "__main__":
    unittest.main()
